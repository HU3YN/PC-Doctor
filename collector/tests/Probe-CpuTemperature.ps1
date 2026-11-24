<#
.SYNOPSIS
    One-time test on a real PC: can PC Doctor read the CPU temperature by
    installing the PawnIO driver for a moment, and does it come off cleanly?

.DESCRIPTION
    NOT part of the collector and not in the collector download. The owner
    runs it once, on their own PC, before this is built into the collector
    (docs/plan.md, Step 1). It answers what could not be checked from a
    development machine:

      * who signed the driver that PawnIO installs, and does Windows load it
        (Memory Integrity, the vulnerable-driver blocklist, Defender)?
      * does LibreHardwareMonitorLib then read a CPU temperature from
        Windows PowerShell 5.1, the shell PCDoctor.cmd uses?
      * does "uninstall" really remove the driver, its service and its files?

    What it does, after you type YES:
      1. Downloads PawnIO's official installer (github.com/namazso/PawnIO.Setup)
         and LibreHardwareMonitorLib with its libraries (nuget.org) into a
         temporary folder, and checks every file against a pinned SHA-256.
      2. Installs PawnIO silently - unless it is already on this PC, in which
         case nothing is installed and nothing is removed.
      3. Reads the CPU's temperature sensors three times.
      4. Uninstalls PawnIO again (only if this script installed it) and checks
         that nothing is left.
      5. Writes runs\cpu-temperature-probe.json next to the collector. It holds
         no computer name, user name or serial number. Attach it to the chat.

    Run it from an administrator PowerShell window:
        powershell -ExecutionPolicy Bypass -File collector\tests\Probe-CpuTemperature.ps1
#>
[CmdletBinding()]
param(
    # Skips the question. For repeat runs only.
    [switch]$Yes,
    # Leaves PawnIO installed at the end even if this script installed it.
    [switch]$KeepInstalled
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# PawnIO 2.2.0.0. The installer itself states "This installer can be
# redistributed unmodified" and is signed by its author (namazso.eu).
$InstallerUrl = 'https://github.com/namazso/PawnIO.Setup/releases/latest/download/PawnIO_setup.exe'
$InstallerSha256 = '1F519A22E47187F70A1379A48CA604981C4FCF694F4E65B734AAA74A9FBA3032'
$UninstallKey = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO'

# LibreHardwareMonitorLib 0.9.6 (MPL-2.0) and everything it needs on
# .NET Framework 4.7.2, as published on nuget.org.
$Packages = @(
    @{ Id = 'librehardwaremonitorlib'; Version = '0.9.6'; Sha256 = '60DB5E0D9135F4658B385CAE139D3B9EAEAC0A8E867D322D20B5DBE4C4039197'; Dll = 'runtimes/win-x64/lib/net472/LibreHardwareMonitorLib.dll' }
    @{ Id = 'diskinfotoolkit'; Version = '1.1.2'; Sha256 = 'A997F0B3701E20B2AB9296E07EE4F74F877E75015277FB6BD314ADE1E2C4DB13'; Dll = 'lib/net472/DiskInfoToolkit.dll' }
    @{ Id = 'hidsharp'; Version = '2.6.4'; Sha256 = 'CF55D4B4D7B42DC1D8496B7B592BA00D1ECD48A70BC07BD8DABD3E9976D108E7'; Dll = 'lib/netstandard2.0/HidSharp.dll' }
    @{ Id = 'ramspdtoolkit-ndd'; Version = '1.4.2'; Sha256 = '57C893824A68C71538055F242586616D4205A671C300897C21B2A6F88270CE64'; Dll = 'lib/net472/RAMSPDToolkit-NDD.dll' }
    @{ Id = 'system.management'; Version = '10.0.2'; Sha256 = 'BB40E7E33254BD2A5FB66B6F476E1E9EA28F0F1C403172696AFDBFB1F8B06221'; Dll = 'lib/netstandard2.0/System.Management.dll' }
    @{ Id = 'system.memory'; Version = '4.6.3'; Sha256 = '26078AEB758C9AE985E8BF851F973026061DA6A5EB4837204D0C2D2204C72955'; Dll = 'lib/net462/System.Memory.dll' }
    @{ Id = 'system.threading.accesscontrol'; Version = '10.0.3'; Sha256 = '9F4F28238E13C6CC47B789A4A1D5647997747594DFCFD45C1526F9B671CDE073'; Dll = 'lib/net462/System.Threading.AccessControl.dll' }
    @{ Id = 'blacksharp.core'; Version = '1.0.7'; Sha256 = '4F713FE18EE7C85A7C49F28309ADAA815714333326AA81FD4D4A81619ECAA0AB'; Dll = 'lib/net472/BlackSharp.Core.dll' }
    @{ Id = 'system.codedom'; Version = '10.0.2'; Sha256 = '30028B346C7B99CCDC484EA7EDBDC7BD038B3C2F007E4E4CBFA3D45768651C2D'; Dll = 'lib/net462/System.CodeDom.dll' }
    @{ Id = 'system.buffers'; Version = '4.6.1'; Sha256 = 'B00451E91D016FBEC091AD1E361F3A7015E1D91D4047F7E48A74455B2A673D79'; Dll = 'lib/net462/System.Buffers.dll' }
    @{ Id = 'system.numerics.vectors'; Version = '4.6.1'; Sha256 = '2BC500A86DCB02F2032D6D877F9E2D6E9E4A79080E57239B4198679D4031F2C7'; Dll = 'lib/net462/System.Numerics.Vectors.dll' }
    @{ Id = 'system.runtime.compilerservices.unsafe'; Version = '6.1.2'; Sha256 = '5F6A7F53AF3465F92BEB6DA873EBE0E496206C313313B98BADEE4355A6B25937'; Dll = 'lib/net462/System.Runtime.CompilerServices.Unsafe.dll' }
    @{ Id = 'system.security.accesscontrol'; Version = '6.0.0'; Sha256 = 'A8EC961016CDAF7123C92F9EB451BCFF331BB8F8C0F8EF9D8BBD7B24FF42C728'; Dll = 'lib/net461/System.Security.AccessControl.dll' }
    @{ Id = 'system.security.principal.windows'; Version = '5.0.0'; Sha256 = '081390C25F6F78592B28ADA853C24514488A221FE9F9A24EFAAF5373643FF3D6'; Dll = 'lib/net461/System.Security.Principal.Windows.dll' }
)

$result = [ordered]@{
    probe          = 'cpu-temperature'
    probe_version  = 2
    ran_at         = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    windows        = $null
    protections    = $null
    cpu            = $null
    downloads      = $null
    pawnio_before  = $null
    install        = $null
    driver_files   = @()
    driver_service = @()
    reading        = $null
    uninstall      = $null
    leftovers      = $null
    cleanup        = $null
    defender       = $null
    errors         = @()
}
$errors = New-Object System.Collections.Generic.List[string]

function Write-Step([string]$Text) { Write-Host "  $Text" }
function Add-ProbeError([string]$Text) {
    $errors.Add($Text)
    Write-Host "  ! $Text" -ForegroundColor Yellow
}
function Get-RegistryValue([string]$Path, [string]$Name) {
    try { return (Get-ItemProperty -LiteralPath $Path -Name $Name -ErrorAction Stop).$Name } catch { return $null }
}
function Get-PawnIOInstall {
    # What the installer registered, or $null when PawnIO is not installed.
    if (-not (Test-Path -LiteralPath $UninstallKey)) { return $null }
    return [ordered]@{
        version  = Get-RegistryValue $UninstallKey 'DisplayVersion'
        location = Get-RegistryValue $UninstallKey 'InstallLocation'
    }
}
function Get-PawnIOServices {
    @(Get-CimInstance -ClassName Win32_SystemDriver -Filter "Name LIKE '%PawnIO%'" -ErrorAction SilentlyContinue | ForEach-Object {
            [ordered]@{ name = $_.Name; state = $_.State; start_mode = $_.StartMode; path = $_.PathName }
        })
}
function Get-PawnIODriverPackages {
    # Driver packages left in Windows' driver store, by their published name.
    try {
        @(Get-CimInstance -ClassName Win32_PnPSignedDriver -Filter "DeviceName LIKE '%PawnIO%'" -ErrorAction Stop | ForEach-Object {
                [ordered]@{ device = $_.DeviceName; device_id = $_.DeviceID; inf = $_.InfName; signer = $_.Signer; version = $_.DriverVersion }
            })
    } catch { @() }
}
function Get-PawnIOLeftovers {
    # What of PawnIO is still on this PC: registration, folder, service,
    # driver package, driver file.
    $left = [ordered]@{
        registered      = [bool](Get-PawnIOInstall)
        folder_exists   = (Test-Path -LiteralPath (Join-Path $env:ProgramFiles 'PawnIO'))
        services        = @(Get-PawnIOServices)
        driver_packages = @(Get-PawnIODriverPackages)
        sys_in_drivers  = @(Get-ChildItem -LiteralPath (Join-Path $env:SystemRoot 'System32\drivers') -Filter '*PawnIO*' -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
    }
    $left.clean = (-not $left.registered) -and (-not $left.folder_exists) -and ($left.services.Count -eq 0) -and
        ($left.driver_packages.Count -eq 0) -and ($left.sys_in_drivers.Count -eq 0)
    return $left
}
function Get-SignatureInfo([string]$Path) {
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    $subject = $null; $issuer = $null
    if ($signature.SignerCertificate) { $subject = $signature.SignerCertificate.Subject; $issuer = $signature.SignerCertificate.Issuer }
    return [ordered]@{
        file      = Split-Path -Leaf $Path
        size      = (Get-Item -LiteralPath $Path).Length
        sha256    = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
        status    = [string]$signature.Status
        type      = [string]$signature.SignatureType
        os_binary = [bool]$signature.IsOSBinary
        subject   = $subject
        issuer    = $issuer
    }
}
function Save-Checked([string]$Url, [string]$Path, [string]$Sha256) {
    Invoke-WebRequest -Uri $Url -OutFile $Path -UseBasicParsing -TimeoutSec 120
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    if ($actual -ne $Sha256) {
        Remove-Item -LiteralPath $Path -Force
        throw "not the expected file (SHA-256 $actual, expected $Sha256): $Url"
    }
}

# ---- before anything is touched -------------------------------------------
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Write-Host ''
Write-Host 'PC Doctor: CPU temperature probe' -ForegroundColor Cyan
if (-not $isAdmin) {
    Write-Host '  This needs an administrator PowerShell window (right-click > Run as administrator).' -ForegroundColor Red
    exit 1
}
Write-Host '  This test INSTALLS a hardware-access driver (PawnIO, by namazso, GPL-2.0),'
Write-Host '  reads the CPU temperature with LibreHardwareMonitorLib, and UNINSTALLS the'
Write-Host '  driver again. If PawnIO is already on this PC it is used and left alone.'
Write-Host '  It downloads from github.com and nuget.org. Close games with anti-cheat first.'
Write-Host ''
if (-not $Yes) {
    $answer = Read-Host '  Type YES to go ahead'
    if ($answer.Trim() -cne 'YES') { Write-Host '  Nothing was changed.'; exit 0 }
}

$os = Get-CimInstance -ClassName Win32_OperatingSystem
$result.windows = [ordered]@{ caption = $os.Caption; version = $os.Version; build = $os.BuildNumber; powershell = $PSVersionTable.PSVersion.ToString() }
$secureBoot = $null
try { $secureBoot = [bool](Confirm-SecureBootUEFI -ErrorAction Stop) } catch { }
$result.protections = [ordered]@{
    secure_boot                 = $secureBoot
    memory_integrity_enabled    = Get-RegistryValue 'HKLM:\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity' 'Enabled'
    vulnerable_driver_blocklist = Get-RegistryValue 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Config' 'VulnerableDriverBlocklistEnable'
}
$result.cpu = @(Get-CimInstance -ClassName Win32_Processor | ForEach-Object { ([string]$_.Name).Trim() })
$result.pawnio_before = Get-PawnIOInstall
$startedAt = Get-Date

$work = Join-Path ([System.IO.Path]::GetTempPath()) ('pcdoctor-probe-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
$libDir = Join-Path $work 'lib'
New-Item -ItemType Directory -Path $libDir -Force | Out-Null
$installedByUs = $false

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

    # ---- 1. downloads ---------------------------------------------------
    Write-Step 'Downloading and checking the files ...'
    $installer = Join-Path $work 'PawnIO_setup.exe'
    Save-Checked $InstallerUrl $installer $InstallerSha256
    $installerSignature = Get-SignatureInfo $installer
    if ($installerSignature.status -ne 'Valid' -or $installerSignature.subject -notmatch 'namazso') {
        throw "the PawnIO installer's signature is not a valid namazso signature ($($installerSignature.status))"
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    foreach ($package in $Packages) {
        $nupkg = Join-Path $work ("{0}.{1}.zip" -f $package.Id, $package.Version)
        Save-Checked ("https://api.nuget.org/v3-flatcontainer/{0}/{1}/{0}.{1}.nupkg" -f $package.Id, $package.Version) $nupkg $package.Sha256
        $archive = [System.IO.Compression.ZipFile]::OpenRead($nupkg)
        try {
            $entry = $archive.Entries | Where-Object { $_.FullName -eq $package.Dll } | Select-Object -First 1
            if (-not $entry) { throw "$($package.Dll) is not in $($package.Id) $($package.Version)" }
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, (Join-Path $libDir (Split-Path -Leaf $package.Dll)), $true)
        } finally { $archive.Dispose() }
    }
    Get-ChildItem -LiteralPath $libDir | Unblock-File
    $result.downloads = [ordered]@{ installer = $installerSignature; libraries = @($Packages | ForEach-Object { "$($_.Id) $($_.Version)" }) }

    # ---- 2. install -----------------------------------------------------
    if ($result.pawnio_before) {
        Write-Step "PawnIO $($result.pawnio_before.version) is already installed: using it, and leaving it installed."
        $result.install = [ordered]@{ skipped = 'already installed' }
    } else {
        Write-Step 'Installing PawnIO (silent) ...'
        $watch = [System.Diagnostics.Stopwatch]::StartNew()
        $process = Start-Process -FilePath $installer -ArgumentList '-install', '-silent' -Wait -PassThru
        $installedByUs = $true
        $after = Get-PawnIOInstall
        $result.install = [ordered]@{ exit_code = $process.ExitCode; seconds = [math]::Round($watch.Elapsed.TotalSeconds, 1); registered = $after }
        if (-not $after) { Add-ProbeError "The installer ended with code $($process.ExitCode) and PawnIO is not registered as installed." }
    }

    $installed = Get-PawnIOInstall
    if ($installed -and $installed.location -and (Test-Path -LiteralPath $installed.location)) {
        $result.driver_files = @(Get-ChildItem -LiteralPath $installed.location -Recurse -File -Include *.sys, *.dll, *.exe, *.cat | ForEach-Object { Get-SignatureInfo $_.FullName })
    }
    $result.driver_service = Get-PawnIOServices
    $result.driver_packages = Get-PawnIODriverPackages
    foreach ($file in $result.driver_files) { Write-Step ("  {0}: signature {1}, {2}" -f $file.file, $file.status, $file.subject) }
    foreach ($service in $result.driver_service) { Write-Step ("  driver service {0}: {1}" -f $service.name, $service.state) }

    # ---- 3. read the CPU temperature, in a separate Windows PowerShell --
    # A separate process, so the driver handles and the libraries are let go
    # before the uninstall, and so this tests the shell PCDoctor.cmd uses.
    Write-Step 'Reading CPU temperature sensors (Windows PowerShell 5.1) ...'
    $reader = Join-Path $work 'read.ps1'
    $readerOut = Join-Path $work 'reading.json'
    @'
param([string]$LibDir, [string]$Out)
$ErrorActionPreference = 'Stop'
$reading = [ordered]@{ loaded = $false; opened = $false; hardware = @(); samples = @(); error = $null; clr = [string][Environment]::Version }
try {
    # Windows PowerShell has no binding redirects: hand .NET the library that
    # sits in this folder whenever it asks for one by name.
    Add-Type -TypeDefinition @"
using System; using System.IO; using System.Reflection;
public static class PCDoctorProbeResolver {
    public static string Dir;
    public static void Enable() {
        AppDomain.CurrentDomain.AssemblyResolve += delegate(object sender, ResolveEventArgs e) {
            string file = Path.Combine(Dir, new AssemblyName(e.Name).Name + ".dll");
            return File.Exists(file) ? Assembly.LoadFrom(file) : null;
        };
    }
}
"@
    [PCDoctorProbeResolver]::Dir = $LibDir
    [PCDoctorProbeResolver]::Enable()
    Add-Type -Path (Join-Path $LibDir 'LibreHardwareMonitorLib.dll')
    $reading.loaded = $true
    $computer = New-Object LibreHardwareMonitor.Hardware.Computer
    $computer.IsCpuEnabled = $true
    $computer.Open()
    $reading.opened = $true
    try {
        foreach ($round in 1..3) {
            $sample = @()
            foreach ($hardware in $computer.Hardware) {
                $hardware.Update()
                if ($round -eq 1) { $reading.hardware += [ordered]@{ type = [string]$hardware.HardwareType; name = [string]$hardware.Name } }
                foreach ($sensor in $hardware.Sensors) {
                    if ([string]$sensor.SensorType -in @('Temperature', 'Power', 'Load', 'Clock')) {
                        $value = $null
                        if ($null -ne $sensor.Value) { $value = [math]::Round([double]$sensor.Value, 1) }
                        $sample += [ordered]@{ type = [string]$sensor.SensorType; name = [string]$sensor.Name; value = $value }
                    }
                }
            }
            $reading.samples += , @($sample)
            Start-Sleep -Seconds 1
        }
    } finally { $computer.Close() }
} catch {
    $reading.error = ($_.Exception.GetType().FullName + ': ' + $_.Exception.Message)
    $inner = $_.Exception.InnerException
    while ($inner) { $reading.error += ' <- ' + $inner.GetType().FullName + ': ' + $inner.Message; $inner = $inner.InnerException }
    if ($_.Exception -is [System.Reflection.ReflectionTypeLoadException]) {
        $reading.error += ' | ' + (($_.Exception.LoaderExceptions | ForEach-Object { $_.Message } | Select-Object -Unique -First 5) -join ' | ')
    }
}
[System.IO.File]::WriteAllText($Out, ($reading | ConvertTo-Json -Depth 6))
'@ | Set-Content -LiteralPath $reader -Encoding UTF8
    $windowsPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    & $windowsPowerShell -NoProfile -ExecutionPolicy Bypass -File $reader -LibDir $libDir -Out $readerOut | Out-Null
    if (Test-Path -LiteralPath $readerOut) {
        $result.reading = Get-Content -LiteralPath $readerOut -Raw | ConvertFrom-Json
        if ($result.reading.error) { Add-ProbeError "Reading failed: $($result.reading.error)" }
        $temperatures = @($result.reading.samples | Select-Object -Last 1 | ForEach-Object { $_ } | Where-Object { $_.type -eq 'Temperature' -and $null -ne $_.value })
        if ($temperatures.Count -gt 0) {
            foreach ($sensor in $temperatures) { Write-Host ("    {0}: {1} C" -f $sensor.name, $sensor.value) -ForegroundColor Green }
        } else {
            Add-ProbeError 'No CPU temperature sensor gave a value.'
        }
    } else {
        Add-ProbeError 'The reading step wrote nothing.'
    }
} catch {
    Add-ProbeError $_.Exception.Message
} finally {
    # ---- 4. uninstall, whatever happened above ----------------------------
    if ($installedByUs -and -not $KeepInstalled) {
        Write-Step 'Uninstalling PawnIO ...'
        try {
            $process = Start-Process -FilePath $installer -ArgumentList '-uninstall', '-silent' -Wait -PassThru
            $result.uninstall = [ordered]@{ exit_code = $process.ExitCode }
        } catch {
            $result.uninstall = [ordered]@{ error = $_.Exception.Message }
            Add-ProbeError "Uninstall could not be started: $($_.Exception.Message)"
        }
        Start-Sleep -Seconds 5
        $result.leftovers = Get-PawnIOLeftovers
        # On Windows Server 2025 (GitHub's runner, 2026-11-24) PawnIO's own
        # uninstaller left its driver package in the driver store and a
        # stopped service. Remove exactly those - PawnIO's device, its oemNN.inf
        # package, its service - and look again.
        if (-not $result.leftovers.clean) {
            $steps = @()
            foreach ($package in @($result.leftovers.driver_packages)) {
                if ($package.device_id) {
                    & pnputil.exe /remove-device $package.device_id | Out-Null
                    $steps += [ordered]@{ step = 'pnputil /remove-device'; exit_code = $LASTEXITCODE }
                }
                if ($package.inf -match '^oem\d+\.inf$') {
                    & pnputil.exe /delete-driver $package.inf /uninstall /force | Out-Null
                    $steps += [ordered]@{ step = "pnputil /delete-driver $($package.inf) /uninstall /force"; exit_code = $LASTEXITCODE }
                }
            }
            foreach ($service in @($result.leftovers.services)) {
                if ($service.name -eq 'PawnIO') {
                    & sc.exe stop PawnIO | Out-Null
                    & sc.exe delete PawnIO | Out-Null
                    $steps += [ordered]@{ step = 'sc delete PawnIO'; exit_code = $LASTEXITCODE }
                }
            }
            Start-Sleep -Seconds 3
            $result.cleanup = [ordered]@{ steps = $steps; leftovers_after = (Get-PawnIOLeftovers) }
        }
        $after = $result.leftovers
        if ($result.cleanup) { $after = $result.cleanup.leftovers_after }
        $clean = $after.clean
        if ($clean) { Write-Host '  PawnIO is gone: no registration, folder, service or driver file left.' -ForegroundColor Green }
        else {
            Add-ProbeError 'Something of PawnIO is still on this PC after the uninstall - see "leftovers" in the result file.'
            Write-Host '  To remove it by hand: Settings > Apps > Installed apps > PawnIO > Uninstall.' -ForegroundColor Yellow
        }
    } elseif ($installedByUs) {
        $result.uninstall = [ordered]@{ skipped = '-KeepInstalled' }
    } else {
        $result.uninstall = [ordered]@{ skipped = 'was not installed by this script' }
    }

    # Did Defender say anything while this ran? Names only.
    try {
        $detections = @(Get-MpThreatDetection -ErrorAction Stop | Where-Object { $_.InitialDetectionTime -ge $startedAt })
        $names = @()
        foreach ($detection in $detections) {
            $threat = Get-MpThreat -ThreatID $detection.ThreatID -ErrorAction SilentlyContinue
            if ($threat) { $names += [string]$threat.ThreatName }
        }
        $result.defender = [ordered]@{ detections = $detections.Count; names = @($names | Select-Object -Unique) }
        if ($detections.Count -gt 0) { Add-ProbeError "Microsoft Defender reported $($detections.Count) detection(s) during the test: $($names -join ', ')" }
    } catch {
        $result.defender = [ordered]@{ unavailable = $_.Exception.Message }
    }

    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    $result.errors = @($errors)

    $runs = Join-Path (Split-Path -Parent $PSScriptRoot) 'runs'
    New-Item -ItemType Directory -Path $runs -Force | Out-Null
    $outFile = Join-Path $runs 'cpu-temperature-probe.json'
    # Paths under a user folder would carry the user's name: none are written,
    # but make sure of it.
    $json = ($result | ConvertTo-Json -Depth 8) -replace '(?i)\\\\Users\\\\[^\\\\"]+', '\\Users\\<user>'
    [System.IO.File]::WriteAllText($outFile, $json, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host ''
    Write-Host "  Result: $outFile" -ForegroundColor Cyan
    Write-Host '  Attach that file to the chat.'
}
if ($errors.Count -gt 0) { exit 1 }
exit 0
