<#
.SYNOPSIS
    Runs the real collector on this PC and checks what it wrote.

.DESCRIPTION
    Used by CI on a Windows runner, and handy after changing the collector:
        .\collector\tests\Invoke-IntegrationTest.ps1 -Mode Quick
        .\collector\tests\Invoke-IntegrationTest.ps1 -Mode Capture -Seconds 8
    It fails (exit 1) if a file is missing or malformed, or if the computer name
    or the user name appears anywhere in the output.
#>
[CmdletBinding()]
param(
    [ValidateSet('Quick', 'Capture')]
    [string]$Mode = 'Quick',
    [int]$Seconds = 8,
    [string]$OutputDir = (Join-Path ([System.IO.Path]::GetTempPath()) ('pcdoctor-it-' + [guid]::NewGuid().ToString('N').Substring(0, 8))),
    # Which PowerShell runs the collector: 'powershell' (5.1) or 'pwsh' (7).
    [string]$Shell = 'powershell',
    # A capture that installs the temperature driver itself, reads through it,
    # and must leave nothing of it behind (needs the files fetch-tools puts in
    # collector/tools).
    [switch]$TemperatureDriver
)

$ErrorActionPreference = 'Stop'
$collector = Join-Path (Split-Path -Parent $PSScriptRoot) 'Collect-PCDoctor.ps1'
$failures = New-Object System.Collections.Generic.List[string]
function Assert-That([bool]$Condition, [string]$Message) {
    if ($Condition) { Write-Host "  ok    $Message" } else { Write-Host "  FAIL  $Message" -ForegroundColor Red; $failures.Add($Message) }
}

Write-Host "Running the collector: $Shell, mode $Mode"
$arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $collector, '-Mode', $Mode, '-OutputDir', $OutputDir,
    '-Label', 'integration test', '-NonInteractive')
if ($Mode -eq 'Capture') { $arguments += @('-Seconds', [string]$Seconds) }
if ($TemperatureDriver) { $arguments += '-InstallTemperatureDriver' }
$watch = [System.Diagnostics.Stopwatch]::StartNew()
& $Shell @arguments
$exitCode = $LASTEXITCODE
Write-Host ("Collector finished in {0:0.0} s with exit code {1}" -f $watch.Elapsed.TotalSeconds, $exitCode)
Assert-That ($exitCode -eq 0) 'collector exits with code 0'

$runDir = @(Get-ChildItem -LiteralPath $OutputDir -Directory -Filter 'PCDoctor-run-*')[0]
$zip = @(Get-ChildItem -LiteralPath $OutputDir -Filter 'PCDoctor-run-*.zip')[0]
Assert-That ($null -ne $runDir) 'a run folder was created'
Assert-That ($null -ne $zip -and $zip.Length -gt 0) 'a zip was created'
if (-not $runDir) { exit 1 }

$expected = @('manifest.json', 'specs.json', 'events.json', 'disks.json', 'collector.log')
if ($Mode -eq 'Capture') { $expected += 'sensors.csv' }
foreach ($name in $expected) { Assert-That (Test-Path (Join-Path $runDir.FullName $name)) "$name exists" }

$allowed = @('manifest.json', 'specs.json', 'events.json', 'disks.json', 'collector.log', 'sensors.csv',
    'sensors_raw.json', 'presentmon.csv')
foreach ($file in Get-ChildItem -LiteralPath $runDir.FullName -File) {
    Assert-That ($allowed -contains $file.Name) "$($file.Name) is a known run file"
}

function Read-Json([string]$Name) {
    $path = Join-Path $runDir.FullName $Name
    $bytes = [System.IO.File]::ReadAllBytes($path)
    Assert-That (-not ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)) "$Name has no byte-order mark"
    return ([System.IO.File]::ReadAllText($path) | ConvertFrom-Json)
}

$manifest = Read-Json 'manifest.json'
Assert-That ($manifest.schema_version -eq 1) 'manifest: schema_version is 1'
Assert-That ($manifest.mode -eq $Mode.ToLowerInvariant()) "manifest: mode is $($Mode.ToLowerInvariant())"
# Checked on the file's text: PowerShell 7 turns date strings into date objects when reading JSON.
$manifestText = [System.IO.File]::ReadAllText((Join-Path $runDir.FullName 'manifest.json'))
Assert-That ($manifestText -match '"started_at":\s*"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ"') 'manifest: started_at is ISO UTC'
Assert-That ($manifest.label -eq 'integration test') 'manifest: label is kept'
Assert-That ($manifest.collector.version -match '^\d+\.\d+\.\d+$') 'manifest: collector version'
Write-Host "  manifest warnings: $(@($manifest.warnings) -join ' | ')"

$specs = Read-Json 'specs.json'
Assert-That (@($specs.cpu).Count -ge 1 -and $specs.cpu[0].name) 'specs: a CPU with a name'
Assert-That ($specs.memory.total_bytes -gt 0) 'specs: memory total'
Assert-That ($specs.memory.modules -is [array]) 'specs: memory modules is a list'
Assert-That ($specs.gpu -is [array]) 'specs: gpu is a list'
Assert-That ($specs.power_plan_guid -match '^[0-9a-f-]{36}$') 'specs: power plan GUID'
Assert-That ($specs.os.caption -and $specs.os.build) 'specs: Windows caption and build'

$events = Read-Json 'events.json'
Assert-That ($events.window_days -eq 30) 'events: window_days'
Assert-That ($events.events -is [array]) 'events: events is a list'
Write-Host "  events collected: $(@($events.events).Count); reader notes: $(@($events.errors) -join ' | ')"
foreach ($item in @($events.events | Select-Object -First 3)) {
    Write-Host ("    {0} {1} #{2} [{3}]" -f $item.time, $item.provider, $item.id, $item.level)
}

$disks = Read-Json 'disks.json'
Assert-That (@($disks.physical_disks).Count -ge 1) 'disks: at least one physical disk'
Assert-That (@($disks.volumes | Where-Object { $_.is_system }).Count -eq 1) 'disks: exactly one system volume'
Assert-That ($disks.physical_disks[0].health_status -match '^(Healthy|Warning|Unhealthy|Unknown)$') 'disks: health status is a word'

if ($Mode -eq 'Capture') {
    $rows = @(Get-Content -LiteralPath (Join-Path $runDir.FullName 'sensors.csv'))
    Assert-That ($rows[0] -match '^elapsed_s,cpu_temp_c,cpu_load_pct,') 'sensors.csv: header'
    Assert-That ($rows.Count -ge 3) "sensors.csv: has samples ($($rows.Count - 1))"
    $columns = $rows[0].Split(',')
    $last = $rows[-1].Split(',')
    Assert-That ($last.Count -eq $columns.Count) 'sensors.csv: every row has every column'
    $cpuLoad = $last[[array]::IndexOf($columns, 'cpu_load_pct')]
    $ram = $last[[array]::IndexOf($columns, 'ram_used_pct')]
    Assert-That ($cpuLoad -match '^\d+(\.\d+)?$') "sensors.csv: CPU load is a number ($cpuLoad)"
    Assert-That ($ram -match '^\d+(\.\d+)?$') "sensors.csv: RAM use is a number ($ram)"
    Write-Host "  sensor source: $($manifest.capture.sensors.source); samples: $($manifest.capture.sensors.samples) in $($manifest.capture.actual_seconds) s"
    Write-Host "  presentmon: used=$($manifest.capture.presentmon.used) exit=$($manifest.capture.presentmon.exit_code) frames=$($manifest.capture.presentmon.frames)"
    Write-Host "  last row: $($rows[-1])"
    Assert-That ($manifest.capture.sensors.samples -eq ($rows.Count - 1)) 'manifest: sample count matches the file'
    Assert-That (-not (Test-Path (Join-Path $runDir.FullName 'presentmon_raw.csv'))) 'the unfiltered PresentMon file is gone'
    if ($TemperatureDriver) {
        $driver = $manifest.capture.temperature_driver
        Write-Host "  temperature driver: $($driver | ConvertTo-Json -Compress)"
        Assert-That ($driver.installed_by_collector -eq $true) 'temperature driver: installed by the collector'
        Assert-That ($driver.removed -eq $true) 'temperature driver: removed after the capture'
        Assert-That ($manifest.capture.sensors.source -eq 'librehardwaremonitorlib') "temperature driver: sensors came through it ($($manifest.capture.sensors.source))"
        Import-Module (Join-Path (Split-Path -Parent $PSScriptRoot) 'PCDoctorCollector.psm1') -Force -DisableNameChecking
        $left = Get-PCDoctorPawnIOLeftovers
        Write-Host "  leftovers: $($left | ConvertTo-Json -Compress)"
        Assert-That ($left.clean) 'temperature driver: nothing of PawnIO is left on the PC'
        Assert-That (-not (Test-Path (Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'PCDoctor\pawnio-installed-by-pcdoctor.txt'))) 'temperature driver: the marker file is gone'
    }
}

# The privacy rule, checked on the real output: no computer name, no user name.
$everything = (Get-ChildItem -LiteralPath $runDir.FullName -File | ForEach-Object { [System.IO.File]::ReadAllText($_.FullName) }) -join "`n"
Assert-That ($everything -notmatch ('(?i)' + [regex]::Escape($env:COMPUTERNAME))) "computer name ($env:COMPUTERNAME) appears nowhere in the run"
Assert-That ($everything -notmatch ('(?i)\b' + [regex]::Escape($env:USERNAME) + '\b')) "user name ($env:USERNAME) appears nowhere in the run"
Assert-That ($everything -notmatch '(?i)serial\s*number\s*[:=]\s*[A-Z0-9]') 'no serial numbers in the run'

Write-Host ''
Write-Host "Run folder: $($runDir.FullName)"
if ($env:GITHUB_OUTPUT) { Add-Content -LiteralPath $env:GITHUB_OUTPUT -Value "run_dir=$($runDir.FullName)" }
if ($failures.Count -gt 0) {
    Write-Host "$($failures.Count) check(s) failed." -ForegroundColor Red
    exit 1
}
Write-Host 'All checks passed.' -ForegroundColor Green
exit 0
