<#
.SYNOPSIS
    Fetches PresentMon (Intel's free, open-source frame-time recorder) into the
    collector's "tools" folder.

.DESCRIPTION
    You do not normally need to run this. The collector download (from a
    release or a PC Doctor server) already has PresentMon inside, and a copy
    without it (from git) runs this script by itself at the first capture.
    Run it by hand to prepare a copy for a PC with no internet access.

    It downloads one file - the PresentMon console program - checks that it is
    the exact file expected (SHA-256) and that Intel signed it, and saves it
    next to the collector. Nothing is installed and no setting is changed:
    delete the "tools" folder to undo it.

    Temperatures come from LibreHardwareMonitor, which this script does NOT
    fetch, because it loads a hardware-access driver and that should be your
    decision. Get it from https://github.com/LibreHardwareMonitor/LibreHardwareMonitor
    and switch on Options > Remote Web Server > Run.

.PARAMETER Version
    PresentMon version to fetch. Change it together with -Sha256.

.PARAMETER Sha256
    Expected SHA-256 of the download. The default matches the default version;
    it was recorded from Intel's release by the windows-facts workflow.
#>
[CmdletBinding()]
param(
    [string]$Version = '2.6.0',
    [string]$Sha256 = 'B2A706BC6AD475749E3B7E3409263AA1E6906D45BDCF993F6DBC0F660188F1AF',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$toolsDir = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'tools'
$fileName = "PresentMon-$Version-x64.exe"
$target = Join-Path $toolsDir $fileName
$url = "https://github.com/GameTechDev/PresentMon/releases/download/v$Version/$fileName"

if ((Test-Path -LiteralPath $target) -and -not $Force) {
    Write-Host "PresentMon $Version is already here: $target"
    exit 0
}

New-Item -ItemType Directory -Path $toolsDir -Force | Out-Null
$download = "$target.download"
Write-Host "Downloading $url"
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $download -UseBasicParsing -TimeoutSec 60
} catch {
    Write-Host "Download failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'You can also download it by hand from https://github.com/GameTechDev/PresentMon/releases'
    Write-Host "and put the PresentMon-...-x64.exe file in: $toolsDir"
    exit 1
}

$actual = (Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash
if ($actual -ne $Sha256.ToUpperInvariant()) {
    Remove-Item -LiteralPath $download -Force
    Write-Host 'The downloaded file is not the one expected, so it was deleted.' -ForegroundColor Red
    Write-Host "  expected SHA-256: $Sha256"
    Write-Host "  actual SHA-256:   $actual"
    exit 1
}

$signature = Get-AuthenticodeSignature -LiteralPath $download
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Intel Corporation') {
    Remove-Item -LiteralPath $download -Force
    Write-Host "The file's signature is not a valid Intel signature ($($signature.Status)), so it was deleted." -ForegroundColor Red
    exit 1
}

Move-Item -LiteralPath $download -Destination $target -Force
Write-Host "Saved and verified (SHA-256 and Intel signature): $target" -ForegroundColor Green
exit 0
