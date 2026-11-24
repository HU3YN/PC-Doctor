<#
.SYNOPSIS
    PC Doctor collector: reads a PC's hardware health and performance data into one folder.

.DESCRIPTION
    READ-ONLY. This script changes no settings, installs nothing and fixes nothing.
    It reads hardware and performance facts and writes them to a run folder (and a
    .zip of it) that the PC Doctor dashboard can diagnose.

    Two modes:
      Quick    About 20 seconds. PC specs, hardware events from the event log,
               disk health. Enough for crashes, shutdowns and failing drives.
      Capture  Quick, plus frame times and sensor readings while a game or stress
               test runs (5 minutes by default). Needed for stutter, overheating
               and CPU/GPU-limit questions.

    Frame times need PresentMon. The collector download includes it; a copy
    without it fetches and checks it at the first capture (Get-Tools.ps1).
    Temperatures need LibreHardwareMonitor running with Options > Remote Web
    Server > Run switched on. Without them the capture still runs with what
    Windows itself can report.

    What is collected, and what never is: docs/privacy.md

.PARAMETER Mode
    Quick or Capture. Without it, the script asks.

.PARAMETER Seconds
    Length of a capture. Default 300 (5 minutes).

.PARAMETER Label
    A note to recognise this run by, e.g. "bench 3, after repaste".
    Never a customer's name.

.PARAMETER Process
    Capture only this program's frames, e.g. "game.exe". Without it, the
    busiest program on screen is kept.

.PARAMETER OutputDir
    Where run folders go. Default: a "runs" folder next to this script.

.PARAMETER UploadUrl
    Address of a PC Doctor server to send the run to, e.g. http://192.168.1.20:8080

.PARAMETER EventDays
    How far back to read the event log. Default 30 days.

.PARAMETER StartDelay
    Seconds to wait before a capture starts, to switch to the game. Default 10
    when run by hand, 0 with -NonInteractive.

.PARAMETER NoDownload
    Never fetch PresentMon, even when it is missing. Frame times are then
    skipped unless it is already in the tools folder.

.PARAMETER InstallTemperatureDriver
    Install the temporary CPU-temperature driver (PawnIO) without asking, for
    unattended captures. It is removed when the capture ends.

.PARAMETER NoTemperatureDriver
    Never offer the temporary CPU-temperature driver.

.PARAMETER NonInteractive
    Ask nothing and wait for nothing (for scripts and tests).

.EXAMPLE
    .\Collect-PCDoctor.ps1
    Asks which mode, then runs it.

.EXAMPLE
    .\Collect-PCDoctor.ps1 -Mode Capture -Seconds 300 -Label "after repaste" -UploadUrl http://localhost:8080
#>
[CmdletBinding()]
param(
    [ValidateSet('Quick', 'Capture')]
    [string]$Mode,
    [ValidateRange(5, 3600)]
    [int]$Seconds = 300,
    [string]$Label = '',
    [string]$Process = '',
    [string]$OutputDir = '',
    [string]$UploadUrl = '',
    [ValidateRange(1, 365)]
    [int]$EventDays = 30,
    [int]$StartDelay = -1,
    [string]$PresentMonPath = '',
    [string]$LhmUrl = 'http://localhost:8085',
    [switch]$NoDownload,
    [switch]$InstallTemperatureDriver,
    [switch]$NoTemperatureDriver,
    [switch]$NoZip,
    [switch]$NonInteractive
)

$ErrorActionPreference = 'Continue'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Import-Module (Join-Path $scriptDir 'PCDoctorCollector.psm1') -Force -DisableNameChecking

$log = New-Object System.Collections.Generic.List[string]
$warnings = New-Object System.Collections.Generic.List[string]

function Write-Step {
    param([string]$Text)
    $log.Add(('{0}  {1}' -f (Get-Date).ToString('HH:mm:ss'), $Text))
    Write-Host "  $Text"
}

function Add-Warning {
    param([string]$Text)
    $warnings.Add($Text)
    $log.Add(('{0}  WARNING: {1}' -f (Get-Date).ToString('HH:mm:ss'), $Text))
    Write-Host "  ! $Text" -ForegroundColor Yellow
}

$interactive = (-not $NonInteractive) -and [Environment]::UserInteractive
$version = Get-PCDoctorCollectorVersion
$isAdmin = Test-PCDoctorAdmin

Write-Host ''
Write-Host "PC Doctor collector $version" -ForegroundColor Cyan
Write-Host 'Read-only: this changes nothing on this PC. It reads hardware and performance data only.'
Write-Host '(One exception, only if you allow it: a capture can install a temperature driver and removes it afterwards.)'
Write-Host ''

# A capture that was cut short (the window closed) can leave behind the
# temperature driver it installed. Remove it now.
if ($isAdmin -and (Test-PCDoctorPawnIOLeftBehind)) {
    Write-Step 'Removing the temperature driver (PawnIO) an earlier PC Doctor capture installed and could not remove ...'
    $earlierTools = Get-PCDoctorTemperatureTools -CollectorDir $scriptDir
    $left = Uninstall-PCDoctorPawnIO -Installer $(if ($earlierTools) { $earlierTools.Installer })
    if ($left.clean) { Write-Step 'Removed.' }
    else { Add-Warning 'The temperature driver (PawnIO) from an earlier capture could not be removed completely. Remove it in Settings > Apps > Installed apps > PawnIO.' }
}

if (-not $isAdmin) {
    Add-Warning 'Not running as administrator: disk wear and temperature counters and frame times may be unavailable. Start PCDoctor.cmd instead to be asked for administrator rights.'
}

# ---- what to do ---------------------------------------------------------
if (-not $Mode) {
    if ($interactive) {
        Write-Host '  1) Quick health check   - about 20 seconds: specs, crash and hardware events, disk health'
        Write-Host '  2) Performance capture  - 5 minutes while a game or stress test runs: adds frame times and sensors'
        $choice = Read-Host '  Choose 1 or 2 [1]'
        if ($choice.Trim() -eq '2') { $Mode = 'Capture' } else { $Mode = 'Quick' }
        if (-not $Label) {
            $Label = Read-Host '  Label for this run - optional, never a customer name (Enter to skip)'
        }
        Write-Host ''
    } else {
        $Mode = 'Quick'
    }
}
$Label = Protect-PCDoctorText -Text $Label -MaxLength 200
if ($StartDelay -lt 0) { $StartDelay = $(if ($interactive -and $Mode -eq 'Capture') { 10 } else { 0 }) }

# ---- where it goes ------------------------------------------------------
if (-not $OutputDir) { $OutputDir = Join-Path $scriptDir 'runs' }
$started = Get-Date
$runName = 'PCDoctor-run-' + $started.ToString('yyyyMMdd-HHmmss')
$runDir = Join-Path $OutputDir $runName
try {
    New-Item -ItemType Directory -Path $runDir -Force -ErrorAction Stop | Out-Null
} catch {
    Write-Host "Cannot create the output folder $runDir : $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# ---- the checks every run does -----------------------------------------
Write-Step 'Reading PC specs ...'
$specs = Get-PCDoctorSpecs
Write-PCDoctorJson -Object $specs -Path (Join-Path $runDir 'specs.json')

Write-Step "Reading hardware events from the last $EventDays days ..."
$eventDocument = Get-PCDoctorEvents -Days $EventDays
Write-PCDoctorJson -Object $eventDocument -Path (Join-Path $runDir 'events.json')
foreach ($problem in @($eventDocument.errors)) { $log.Add("Event log: $problem") }

Write-Step 'Reading disk health ...'
$disks = Get-PCDoctorDisks
foreach ($problem in @($disks.warnings)) { Add-Warning $problem }
$disks.Remove('warnings')
Write-PCDoctorJson -Object $disks -Path (Join-Path $runDir 'disks.json')

# ---- the capture --------------------------------------------------------
$capture = $null
$temperatureDriver = $null
$lhmReader = $null
function Stop-TemperatureDriver {
    # Ends the sensor reader and removes the driver if this run installed it.
    # Runs once, at the end of the capture or when it is cut short (Ctrl+C).
    if ($script:lhmReader) { Stop-PCDoctorLhmReader -Reader $script:lhmReader; $script:lhmReader = $null }
    $driver = $script:temperatureDriver
    if ($driver -and $driver.installed_by_collector -and $null -eq $driver.removed) {
        Write-Step 'Removing the temperature driver (PawnIO) ...'
        $left = Uninstall-PCDoctorPawnIO -Installer $driver.installer_path -Inf $driver.package
        $driver.removed = [bool]$left.clean
        if ($left.clean) { Write-Step 'The temperature driver is removed: nothing of it is left on this PC.' }
        else { Add-Warning 'The temperature driver (PawnIO) could not be removed completely. PC Doctor tries again on its next run as administrator; or remove it in Settings > Apps > Installed apps > PawnIO.' }
    }
}

if ($Mode -eq 'Capture') {
  try {
    $found = Find-PCDoctorPresentMon -ExplicitPath $PresentMonPath -ToolsDir (Join-Path $scriptDir 'tools') -Elevated:$isAdmin
    $presentMon = $found.Path
    if ($found.Problem) {
        Add-Warning $found.Problem
    } elseif (-not $presentMon -and -not $PresentMonPath -and -not $NoDownload) {
        # The download from a PC Doctor server and the release both carry
        # PresentMon. A copy from git does not, so fetch it here instead of
        # sending the person off to run another script. Get-Tools.ps1 keeps
        # the file only if it has the pinned SHA-256 and Intel's signature.
        Write-Step 'PresentMon (frame times) is not in this folder: fetching it from github.com and checking it ...'
        try { & (Join-Path $scriptDir 'Get-Tools.ps1') | ForEach-Object { $log.Add("Get-Tools: $_") } } catch { $log.Add("Get-Tools: $($_.Exception.Message)") }
        $found = Find-PCDoctorPresentMon -ToolsDir (Join-Path $scriptDir 'tools') -Elevated:$isAdmin
        $presentMon = $found.Path
        if ($found.Problem) { Add-Warning $found.Problem }
    }
    if ($found.Problem) {
        $presentMon = $null   # reported above
    } elseif (-not $presentMon) {
        Add-Warning 'PresentMon could not be found or fetched, so frame times are skipped. Use the collector download from a release or a PC Doctor server, which includes it.'
    } elseif (-not $isAdmin) {
        Add-Warning 'PresentMon needs administrator rights to record frame times; it may record nothing.'
    }

    # Decide once where sensor readings come from.
    $nvidiaSmi = $null
    $gpuPrefix = $null
    $first = Get-PCDoctorLhmSensors -Url $LhmUrl
    if ($first) {
        $sensorSource = 'librehardwaremonitor'
        $gpuPrefix = Select-PCDoctorGpuPrefix $first
        # One snapshot of sensor names (no values that identify anyone), so a
        # wrong mapping on unusual hardware can be diagnosed later.
        Write-PCDoctorJson -Object @{ sensors = @($first | Select-Object SensorId, Type, Text, Value) } -Path (Join-Path $runDir 'sensors_raw.json')
        Write-Step 'Sensors: LibreHardwareMonitor'
    } else {
        # No LibreHardwareMonitor running: read the sensors ourselves, through
        # the PawnIO driver - already on the PC, or installed now if allowed.
        $tempTools = $null
        if (-not $NoTemperatureDriver) { $tempTools = Get-PCDoctorTemperatureTools -CollectorDir $scriptDir }
        if ($tempTools -and $tempTools.Problem) { Add-Warning $tempTools.Problem; $tempTools = $null }
        if ($tempTools -and $isAdmin) {
            $already = Test-PCDoctorPawnIOInstalled
            $temperatureDriver = [ordered]@{
                name = 'PawnIO'; version = $tempTools.Version; already_installed = $already
                asked = $false; installed_by_collector = $false; removed = $null; package = $null; installer_path = $tempTools.Installer
            }
            $useDriver = $already
            if (-not $already) {
                if ($InstallTemperatureDriver) {
                    $useDriver = $true
                } elseif ($interactive) {
                    $temperatureDriver.asked = $true
                    Write-Host ''
                    Write-Host '  CPU temperature: Windows does not give it to programs. PC Doctor can install a' -ForegroundColor Cyan
                    Write-Host '  hardware-monitoring driver (PawnIO, signed through Microsoft) for this capture' -ForegroundColor Cyan
                    Write-Host '  and remove it when the capture ends. Close games with anti-cheat first.' -ForegroundColor Cyan
                    $answer = Read-Host '  Install it for this capture? [y/N]'
                    $useDriver = ([string]$answer).Trim() -match '^(y|yes)$'
                }
                if ($useDriver) {
                    Write-Step "Installing the temperature driver (PawnIO $($tempTools.Version)) ..."
                    $package = Install-PCDoctorPawnIO -Installer $tempTools.Installer
                    if ($package) {
                        $temperatureDriver.installed_by_collector = $true
                        $temperatureDriver.package = $package
                    } else {
                        Add-Warning 'The temperature driver (PawnIO) could not be installed, so there is no CPU temperature in this run.'
                        $useDriver = $false
                    }
                }
            }
            if ($useDriver) {
                $lhmReader = Start-PCDoctorLhmReader -LibraryDir $tempTools.LibraryDir
                $wait = [System.Diagnostics.Stopwatch]::StartNew()
                # Starting it compiles a little code, opens the hardware and
                # reads every sensor once: allow time on a slow PC.
                while ($lhmReader -and -not $first -and $wait.Elapsed.TotalSeconds -lt 45) {
                    Start-Sleep -Milliseconds 500
                    $first = Get-PCDoctorLhmReaderSensors -Reader $lhmReader
                    if (-not $first -and $lhmReader.Process.HasExited) { break }
                }
                if ($first) {
                    $sensorSource = 'librehardwaremonitorlib'
                    $gpuPrefix = Select-PCDoctorGpuPrefix $first
                    Write-PCDoctorJson -Object @{ sensors = @($first | Select-Object SensorId, Type, Text, Value) } -Path (Join-Path $runDir 'sensors_raw.json')
                    Write-Step 'Sensors: LibreHardwareMonitorLib through PawnIO'
                    $skippedFile = $lhmReader.OutFile + '.skipped'
                    if (Test-Path -LiteralPath $skippedFile) {
                        Write-Step ('  Sensor groups this PC could not open: ' + (Protect-PCDoctorText -Text ([System.IO.File]::ReadAllText($skippedFile)) -MaxLength 300))
                    }
                } else {
                    Add-Warning ('The temperature reader gave no sensors ({0}), so there is no CPU temperature in this run.' -f (Get-PCDoctorLhmReaderProblem -Reader $lhmReader))
                    Stop-TemperatureDriver
                }
            }
        }
        if ($sensorSource -ne 'librehardwaremonitorlib') {
            $nvidiaSmi = Find-PCDoctorNvidiaSmi -Elevated:$isAdmin
            $sensorSource = $(if ($nvidiaSmi) { 'windows+nvidia-smi' } else { 'windows' })
            if ($nvidiaSmi) {
                # Cross-check, for the log only: the GPU temperature Windows'
                # own adapter counters give (what AMD and Intel cards rely on)
                # next to nvidia-smi's, on the same card.
                $check = Get-PCDoctorWindowsSample -NvidiaSmi $nvidiaSmi
                $windowsTemps = @(Get-PCDoctorGpuPerf | Where-Object { $null -ne $_.temperature_c } | ForEach-Object { '{0:0.0} C' -f $_.temperature_c })
                $log.Add(('GPU temperature cross-check: nvidia-smi {0}; Windows adapter counters {1}' -f
                    $(if ($null -ne $check['gpu_temp_c']) { '{0:0.0} C' -f $check['gpu_temp_c'] } else { 'none' }),
                    $(if ($windowsTemps.Count) { $windowsTemps -join ', ' } else { 'none' })))
            }
            if (-not ($temperatureDriver -and $temperatureDriver.installed_by_collector)) {
                Add-Warning 'There is no CPU temperature in this run: allow the temperature driver when asked (as administrator), or start LibreHardwareMonitor with Options > Remote Web Server > Run.'
            }
        }
    }

    if ($StartDelay -gt 0) {
        Write-Host ''
        Write-Host "  Switch to your game or stress test now. Capturing $Seconds seconds, starting in $StartDelay ..." -ForegroundColor Cyan
        for ($remaining = $StartDelay; $remaining -gt 0; $remaining--) {
            Write-Host ("`r  Starting in {0,2} s " -f $remaining) -NoNewline
            Start-Sleep -Seconds 1
        }
        Write-Host "`r  Capturing ...          "
    }

    # Is anything running? Checked now, not after the capture: the first real
    # capture of this project recorded five minutes of an idle desktop.
    $readSample = {
        if ($sensorSource -eq 'librehardwaremonitor') {
            ConvertTo-PCDoctorSample -Sensors (Get-PCDoctorLhmSensors -Url $LhmUrl) -GpuPrefix $gpuPrefix
        } elseif ($sensorSource -eq 'librehardwaremonitorlib') {
            ConvertTo-PCDoctorSample -Sensors (Get-PCDoctorLhmReaderSensors -Reader $lhmReader) -GpuPrefix $gpuPrefix
        } else {
            Get-PCDoctorWindowsSample -NvidiaSmi $nvidiaSmi
        }
    }
    $loadSamples = New-Object System.Collections.Generic.List[object]
    foreach ($i in 1..3) { $loadSamples.Add((& $readSample)); Start-Sleep -Milliseconds 700 }
    $load = Test-PCDoctorUnderLoad -Samples $loadSamples
    $waited = 0
    if ($load.busy -eq $false -and $interactive) {
        Write-Host ''
        Write-Host ("  Nothing seems to be running ({0})." -f (Format-PCDoctorLoad $load)) -ForegroundColor Yellow
        Write-Host '  Start your game or stress test: the capture begins by itself once it is under load.' -ForegroundColor Yellow
        Write-Host '  Press Enter to capture anyway. Waiting up to 3 minutes ...' -ForegroundColor Yellow
        $waitWatch = [System.Diagnostics.Stopwatch]::StartNew()
        while ($load.busy -eq $false -and $waitWatch.Elapsed.TotalSeconds -lt 180) {
            $pressed = $false
            try { while ([Console]::KeyAvailable) { if ([Console]::ReadKey($true).Key -eq 'Enter') { $pressed = $true } } } catch { }
            if ($pressed) { break }
            # Three fresh readings in a row, so one busy second (a loading
            # screen, a window opening) does not start the capture.
            $loadSamples.Clear()
            foreach ($i in 1..3) { $loadSamples.Add((& $readSample)); Start-Sleep -Milliseconds 700 }
            $load = Test-PCDoctorUnderLoad -Samples $loadSamples
            Write-Host ("`r  Waiting for load: {0}        " -f (Format-PCDoctorLoad $load)) -NoNewline
        }
        Write-Host ''
        $waited = [int]$waitWatch.Elapsed.TotalSeconds
    }
    if ($load.busy -eq $false) {
        Add-Warning ("The PC looked idle when the capture started ({0}). Without a game or stress test running, the performance checks have nothing to judge." -f (Format-PCDoctorLoad $load))
    } elseif ($load.busy) {
        Write-Step ("Under load ({0}): capturing." -f (Format-PCDoctorLoad $load))
    }

    $rawCsv = Join-Path $runDir 'presentmon_raw.csv'
    $pmOut = Join-Path $runDir 'presentmon_stdout.txt'
    $pmErr = Join-Path $runDir 'presentmon_stderr.txt'
    $pmProcess = $null
    $pmVersion = $null
    if ($presentMon) {
        try { $pmVersion = (Get-Item -LiteralPath $presentMon).VersionInfo.ProductVersion } catch { }
        # The standalone build carries no version resource; its file name does.
        if (-not $pmVersion -and (Split-Path -Leaf $presentMon) -match '(\d+\.\d+\.\d+)') { $pmVersion = $Matches[1] }
        $pmArguments = Get-PCDoctorPresentMonArguments -OutputFile $rawCsv -Seconds $Seconds -Process $Process
        try {
            # PresentMon prints its banner on stderr. Its output goes to files:
            # merging it with 2>&1 turns that banner into a PowerShell error.
            $pmProcess = Start-Process -FilePath $presentMon -ArgumentList $pmArguments -PassThru -NoNewWindow `
                -RedirectStandardOutput $pmOut -RedirectStandardError $pmErr -ErrorAction Stop
            $null = $pmProcess.Handle   # keeps the exit code readable after it ends
            Write-Step "Frame times: PresentMon $pmVersion"
        } catch {
            Add-Warning "PresentMon could not be started: $($_.Exception.Message)"
            $pmProcess = $null
        }
    }

    Write-Step "Capturing for $Seconds seconds ..."
    $rows = New-Object System.Collections.Generic.List[string]
    $rows.Add((Get-PCDoctorSensorHeader))
    $interval = 1.0
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $tick = 0
    while ($watch.Elapsed.TotalSeconds -lt $Seconds) {
        $elapsed = $watch.Elapsed.TotalSeconds
        $sample = & $readSample
        $rows.Add((Format-PCDoctorSensorRow -ElapsedSeconds $elapsed -Sample $sample))
        if ($interactive) {
            $percent = [int][math]::Min(100, 100 * $watch.Elapsed.TotalSeconds / $Seconds)
            Write-Progress -Activity 'PC Doctor capture' -Status ("{0:0} of {1} seconds" -f $watch.Elapsed.TotalSeconds, $Seconds) -PercentComplete $percent
        }
        $tick++
        $wait = ($tick * $interval) - $watch.Elapsed.TotalSeconds
        if ($wait -gt 0) { Start-Sleep -Milliseconds ([int]($wait * 1000)) }
    }
    $actualSeconds = [math]::Round($watch.Elapsed.TotalSeconds, 1)
    if ($interactive) { Write-Progress -Activity 'PC Doctor capture' -Completed }
    [System.IO.File]::WriteAllLines((Join-Path $runDir 'sensors.csv'), $rows, (New-Object System.Text.UTF8Encoding($false)))
    $sampleCount = $rows.Count - 1

    $pmInfo = [ordered]@{ used = $false; version = $pmVersion; file = $null; exit_code = $null; frames = 0; other_processes_removed = 0 }
    $targetProcess = $(if ($Process) { $Process } else { $null })
    if ($pmProcess) {
        Write-Step 'Waiting for PresentMon to finish ...'
        if (-not $pmProcess.WaitForExit(30000)) {
            Add-Warning 'PresentMon did not stop by itself and was closed.'
            try { $pmProcess.Kill() } catch { }
        }
        try { $pmInfo.exit_code = $pmProcess.ExitCode } catch { }
        foreach ($file in @($pmOut, $pmErr)) {
            if (Test-Path -LiteralPath $file) {
                foreach ($line in @(Get-Content -LiteralPath $file -ErrorAction SilentlyContinue | Select-Object -First 15)) {
                    if ($line.Trim()) { $log.Add('PresentMon: ' + (Protect-PCDoctorText -Text $line -MaxLength 200)) }
                }
                Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue
            }
        }
        if (Test-Path -LiteralPath $rawCsv) {
            $kept = Select-PCDoctorPresentMonRows -Path $rawCsv -Destination (Join-Path $runDir 'presentmon.csv') -Process $Process
            Remove-Item -LiteralPath $rawCsv -Force -ErrorAction SilentlyContinue
            if ($kept.frames -gt 0) {
                $pmInfo.used = $true
                $pmInfo.file = 'presentmon.csv'
                $pmInfo.frames = $kept.frames
                $pmInfo.other_processes_removed = $kept.other_processes_removed
                $targetProcess = $kept.application
                Write-Step ("Frame times: {0} frames from {1}" -f $kept.frames, $kept.application)
            } else {
                Remove-Item -LiteralPath (Join-Path $runDir 'presentmon.csv') -Force -ErrorAction SilentlyContinue
                Add-Warning 'PresentMon recorded no frames. Was the game running and on screen during the capture?'
            }
        } else {
            Add-Warning 'PresentMon wrote no frame-time file. Nothing was drawing to the screen during the capture, or it lacked administrator rights.'
        }
    }

    Stop-TemperatureDriver
    $driverRecord = $null
    if ($temperatureDriver) {
        $driverRecord = [ordered]@{}
        foreach ($key in @('name', 'version', 'already_installed', 'asked', 'installed_by_collector', 'removed')) { $driverRecord[$key] = $temperatureDriver[$key] }
    }
    $capture = [ordered]@{
        requested_seconds = $Seconds
        actual_seconds    = $actualSeconds
        target_process    = $targetProcess
        load_at_start     = [ordered]@{ busy = $load.busy; gpu_load_pct = $load.gpu_load_pct; cpu_load_pct = $load.cpu_load_pct; waited_seconds = $waited }
        presentmon        = $pmInfo
        temperature_driver = $driverRecord
        sensors           = [ordered]@{
            source           = $sensorSource
            interval_seconds = $interval
            file             = 'sensors.csv'
            samples          = $sampleCount
        }
    }
  } finally {
    # Also when the capture is stopped with Ctrl+C: never leave the driver.
    Stop-TemperatureDriver
  }
}

# ---- manifest, log, zip -------------------------------------------------
$finished = Get-Date
$manifest = [ordered]@{
    schema_version    = Get-PCDoctorSchemaVersion
    run_id            = [guid]::NewGuid().ToString()
    collector         = [ordered]@{ name = 'pcdoctor-collector-ps'; version = $version; powershell = $PSVersionTable.PSVersion.ToString() }
    started_at        = ConvertTo-PCDoctorIsoTime $started
    finished_at       = ConvertTo-PCDoctorIsoTime $finished
    mode              = $Mode.ToLowerInvariant()
    label             = $Label
    capture           = $capture
    event_window_days = $EventDays
    is_admin          = $isAdmin
    warnings          = @($warnings)
}
Write-PCDoctorJson -Object $manifest -Path (Join-Path $runDir 'manifest.json')
[System.IO.File]::WriteAllLines((Join-Path $runDir 'collector.log'), $log, (New-Object System.Text.UTF8Encoding($false)))

$zipPath = $null
if (-not $NoZip) {
    $zipPath = Join-Path $OutputDir ($runName + '.zip')
    try {
        Compress-Archive -Path (Join-Path $runDir '*') -DestinationPath $zipPath -Force -ErrorAction Stop
    } catch {
        Add-Warning "Could not create the zip: $($_.Exception.Message)"
        $zipPath = $null
    }
}

# ---- what was found, in plain numbers ----------------------------------
$summary = Get-PCDoctorEventSummary -EventDocument $eventDocument
Write-Host ''
Write-Host "  In the last $EventDays days:" -ForegroundColor Cyan
$lines = @(
    @('Fatal/corrected hardware errors (WHEA)', $summary.whea_errors),
    @('Unexpected shutdowns (Kernel-Power 41)', $summary.unexpected_shutdowns),
    @('Thermal shutdowns', $summary.thermal_shutdowns),
    @('Blue screens', $summary.blue_screens),
    @('Disk / file-system error events', $summary.disk_errors),
    @('Graphics driver resets', $summary.display_resets),
    @('Failed memory tests', $summary.memory_test_failures)
)
foreach ($line in $lines) {
    $color = $(if ([int]$line[1] -gt 0) { 'Yellow' } else { 'Gray' })
    Write-Host ('    {0,-42} {1}' -f $line[0], $line[1]) -ForegroundColor $color
}
if (@($summary.stop_codes).Count -gt 0) {
    Write-Host ('    Stop codes: ' + (@($summary.stop_codes) -join ', ')) -ForegroundColor Yellow
}
$unhealthy = @($disks.physical_disks | Where-Object { $_.health_status -and $_.health_status -ne 'Healthy' })
foreach ($disk in $unhealthy) {
    Write-Host ("    Disk '{0}' reports health: {1}" -f $disk.name, $disk.health_status) -ForegroundColor Yellow
}
Write-Host ''
Write-Host "  Run folder: $runDir"
if ($zipPath) { Write-Host "  Zip file:   $zipPath" -ForegroundColor Green }

# ---- upload -------------------------------------------------------------
$uploadFailed = $false
if ($UploadUrl -and $zipPath) {
    Write-Host "  Uploading to $UploadUrl ..."
    try {
        $answer = Send-PCDoctorRun -ZipPath $zipPath -Url $UploadUrl -Label $Label
        # A guest upload comes back with the key of a private link to this one run.
        $link = Get-PCDoctorResultLink -BaseUrl $UploadUrl -Answer $answer
        if (-not $link) {
            Write-Host '  Uploaded, but the server did not send back a usable link. Open the dashboard to see the run.' -ForegroundColor Yellow
        } elseif ($answer.share_key) {
            Write-Host "  Uploaded. Your private diagnosis link:" -ForegroundColor Green
            Write-Host "  $link" -ForegroundColor Green
            if ($isAdmin) {
                # Never start a browser from an administrator process: copy the link instead.
                Write-Host '  Open it in your browser (it is not opened from here, because this window runs as administrator).'
            } elseif ([Environment]::UserInteractive -and -not $NonInteractive) {
                Start-Process $link
            }
        } else {
            Write-Host "  Uploaded. Diagnosis: $link" -ForegroundColor Green
        }
        Write-Host ('  {0}: {1}' -f ([string]$answer.run.verdict).ToUpperInvariant(), $answer.run.headline)
    } catch {
        $uploadFailed = $true
        Write-Host "  Upload failed: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host '  The zip is still on disk - drop it on the dashboard instead.'
    }
} elseif ($zipPath) {
    Write-Host '  Next: take this zip to the master PC and drop it on the Runs page of the dashboard.'
    Write-Host '  (If the collector is on a USB stick, the zip is already on the stick.)'
}
Write-Host ''
if ($uploadFailed) { exit 2 }
exit 0
