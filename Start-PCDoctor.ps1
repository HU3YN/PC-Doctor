<#
.SYNOPSIS
    Starts PC Doctor on this computer - the "master" PC that holds the dashboard,
    the diagnoses and the work log.

.DESCRIPTION
    Uses Docker when Docker Desktop is running, and plain Python when it is not,
    so it works either way. The first start sets things up and takes a few
    minutes; later starts take seconds.

      Docker route   needs Docker Desktop running. Includes photo reading.
      Python route   needs Python 3.11+ and (first time only) Node.js 20+.
                     Photo reading also needs the Tesseract OCR program.

    Your data stays on this computer: in Docker volumes, or in the "data" folder.

.PARAMETER Lan
    Let other PCs on your network open the dashboard, download the collector
    from it and upload runs to it. There are NO LOGINS yet, so use this only on
    a network you trust (home, the shop bench) - never on public Wi-Fi.

.PARAMETER Mode
    Auto (default), Docker or Python.

.PARAMETER Port
    Port for the dashboard. Default 8080.

.PARAMETER Check
    Start it, check that it answers, and stop again (used by CI).

.EXAMPLE
    .\Start-PCDoctor.ps1
    .\Start-PCDoctor.ps1 -Lan
#>
[CmdletBinding()]
param(
    [ValidateSet('Auto', 'Docker', 'Python')]
    [string]$Mode = 'Auto',
    [switch]$Lan,
    [int]$Port = 8080,
    [switch]$Check,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root

function Write-Info([string]$Text) { Write-Host "  $Text" }
function Stop-WithMessage([string]$Text) {
    Write-Host ''
    Write-Host "  $Text" -ForegroundColor Red
    exit 1
}

function Test-DockerRunning {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { return $false }
    # Through cmd so docker's error text (engine not running) never becomes a PowerShell error.
    & cmd.exe /c 'docker info >nul 2>&1'
    return ($LASTEXITCODE -eq 0)
}

function Find-Python {
    foreach ($candidate in @(@('py', '-3'), @('python'), @('python3'))) {
        if (-not (Get-Command $candidate[0] -ErrorAction SilentlyContinue)) { continue }
        $arguments = @()
        if ($candidate.Count -gt 1) { $arguments = @($candidate[1..($candidate.Count - 1)]) }
        # "--version" needs no quoting: Windows PowerShell strips double quotes
        # from arguments passed to programs, which breaks "python -c" snippets.
        $version = (& $candidate[0] @arguments --version 2>$null | Out-String)
        if ($LASTEXITCODE -eq 0 -and $version -match 'Python (\d+)\.(\d+)') {
            if ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 11) { return , @($candidate) }
        }
    }
    return $null
}

function Get-LanAddresses {
    try {
        return @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
                Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
                ForEach-Object { $_.IPAddress })
    } catch { return @() }
}

function Wait-ForHealth([string]$Url, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $answer = Invoke-RestMethod -Uri "$Url/api/health" -TimeoutSec 3 -ErrorAction Stop
            if ($answer.status -eq 'ok') { return $true }
        } catch { }
        Start-Sleep -Seconds 2
    }
    return $false
}

Write-Host ''
Write-Host 'PC Doctor - master computer' -ForegroundColor Cyan
Write-Host ''

$dockerRunning = Test-DockerRunning
$python = Find-Python
if ($Mode -eq 'Auto') {
    if ($dockerRunning) { $Mode = 'Docker' }
    elseif ($python) { $Mode = 'Python' }
    else {
        Stop-WithMessage ('Neither Docker nor Python was found. Install one of them:' + "`n" +
            '    Docker Desktop (start it and wait for "Engine running"), or' + "`n" +
            '    Python 3.11 or newer from python.org (tick "Add python.exe to PATH").')
    }
}

$bind = '127.0.0.1'
if ($Lan) { $bind = '0.0.0.0' }
$url = "http://localhost:$Port"

if ($Mode -eq 'Docker') {
    if (-not $dockerRunning) {
        Stop-WithMessage 'Docker is not running. Open Docker Desktop, wait until it says "Engine running", and try again - or run this with -Mode Python.'
    }
    Write-Info 'Starting with Docker (the first time builds for a few minutes) ...'
    $env:PCDOCTOR_BIND = $bind
    $env:PCDOCTOR_PORT = [string]$Port
    & docker compose up -d --build --wait --wait-timeout 300
    if ($LASTEXITCODE -ne 0) { Stop-WithMessage 'Docker could not start PC Doctor. The lines above say why.' }
    $server = $null
} else {
    if (-not $python) { Stop-WithMessage 'Python 3.11 or newer was not found. Install it from python.org and tick "Add python.exe to PATH".' }
    $venvPython = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Info 'First start: creating a private Python environment ...'
        $pythonArguments = @()
        if ($python.Count -gt 1) { $pythonArguments = @($python[1..($python.Count - 1)]) }
        & $python[0] @pythonArguments -m venv (Join-Path $root '.venv')
        if (-not (Test-Path -LiteralPath $venvPython)) { Stop-WithMessage 'Could not create the Python environment.' }
    }
    # Quick to repeat: pip skips what is already installed. Keeps the app in step after "git pull".
    Write-Info 'Checking the Python packages ...'
    & $venvPython -m pip install --quiet --disable-pip-version-check -e workers -e 'api[photo]'
    if ($LASTEXITCODE -ne 0) { Stop-WithMessage 'Installing the Python packages failed. The lines above say why.' }

    $index = Join-Path $root 'web\dist\index.html'
    if (-not (Test-Path -LiteralPath $index)) {
        if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
            Stop-WithMessage 'The dashboard has not been built yet and Node.js was not found. Install Node.js 20 or newer from nodejs.org (needed once), or use Docker.'
        }
        Write-Info 'First start: building the dashboard (a minute or two) ...'
        & cmd.exe /c 'npm --prefix web ci --no-audit --no-fund && npm --prefix web run build'
        if (-not (Test-Path -LiteralPath $index)) { Stop-WithMessage 'Building the dashboard failed. The lines above say why.' }
    }

    $env:PCDOCTOR_DATA_DIR = Join-Path $root 'data'
    Write-Info 'Starting PC Doctor ...'
    $server = Start-Process -FilePath $venvPython -ArgumentList @('-m', 'pcdoctor_api', '--host', $bind, '--port', [string]$Port) `
        -WorkingDirectory $root -PassThru -NoNewWindow
}

if (-not (Wait-ForHealth -Url $url -Seconds 90)) {
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue }
    Stop-WithMessage "PC Doctor did not answer at $url. Is something else using port $Port? Try -Port 8090."
}

Write-Host ''
Write-Host "  PC Doctor is running:  $url" -ForegroundColor Green
if ($Lan) {
    foreach ($address in (Get-LanAddresses)) {
        Write-Host "  From other PCs on this network:  http://${address}:$Port" -ForegroundColor Green
    }
    Write-Host '  It uses plain HTTP: anyone on this network can reach the sign-in page. Trusted networks only.' -ForegroundColor Yellow
    Write-Host '  If other PCs cannot connect, allow it through Windows Firewall when Windows asks.'
} else {
    Write-Host '  Only this computer can open it. Start with -Lan to let other PCs on your network in.'
}

# First start: the code needed to create the master account.
$setupCode = $null
try {
    if ((Invoke-RestMethod -Uri "$url/api/auth/status" -TimeoutSec 5).setup_needed) {
        if ($Mode -eq 'Docker') { $setupCode = (& docker compose exec -T api cat /data/setup-code.txt 2>$null | Out-String).Trim() }
        else {
            $codeFile = Join-Path $root 'data\setup-code.txt'
            if (Test-Path -LiteralPath $codeFile) { $setupCode = (Get-Content -LiteralPath $codeFile -Raw).Trim() }
        }
    }
} catch { }
if ($setupCode) {
    Write-Host ''
    Write-Host "  First start - create your master account in the browser. Setup code:  $setupCode" -ForegroundColor Cyan
}

if ($Check) {
    Write-Info 'Check passed.'
    if ($server) { Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue }
    elseif ($Mode -eq 'Docker') { & docker compose down | Out-Null }
    exit 0
}

if (-not $NoBrowser) { Start-Process $url }
if ($server) {
    Write-Host ''
    Write-Host '  Leave this window open while you use PC Doctor. Close it (or press Ctrl+C) to stop.'
    try { $server.WaitForExit() } finally {
        if (-not $server.HasExited) { Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue }
    }
} else {
    Write-Host ''
    Write-Host '  It keeps running in Docker. To stop it:  docker compose down   (your data is kept)'
}
