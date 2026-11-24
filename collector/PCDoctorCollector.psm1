# PC Doctor collector - functions.
#
# READ-ONLY BY DESIGN. Nothing in this file changes a setting, installs
# anything, or runs a fix. It reads hardware and performance facts and writes
# them to a folder. docs/privacy.md lists exactly what is read and what never is.
#
# Works on Windows PowerShell 5.1 (on every Windows 10/11 PC) and PowerShell 7.
# Keep this file plain ASCII: Windows PowerShell 5.1 misreads UTF-8 without a
# byte-order mark, so a single accented character can break the script.

# GitHub Actions and some shells set this to 'Stop' globally. Every risky call
# below has its own try/catch, so one unreadable sensor never ends the run.
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

$script:CollectorVersion = '0.1.0'
$script:SchemaVersion = 1
$script:Invariant = [System.Globalization.CultureInfo]::InvariantCulture

# Column order of sensors.csv. The analyzer reads columns by name.
$script:SensorColumns = @(
    'cpu_temp_c', 'cpu_load_pct', 'cpu_core_max_load_pct', 'cpu_clock_mhz', 'cpu_perf_pct',
    'cpu_power_w', 'gpu_temp_c', 'gpu_hotspot_c', 'gpu_load_pct', 'gpu_clock_mhz',
    'gpu_power_w', 'gpu_fan_rpm', 'gpu_vram_used_pct', 'ram_used_pct'
)

# Windows shell processes that present frames but are never what is tested.
$script:ShellProcesses = @(
    'dwm.exe', 'explorer.exe', 'searchhost.exe', 'searchapp.exe', 'shellexperiencehost.exe',
    'startmenuexperiencehost.exe', 'textinputhost.exe', 'applicationframehost.exe',
    'systemsettings.exe', 'lockapp.exe', 'widgets.exe', 'taskmgr.exe', 'presentmon.exe'
)

# Which events are read from the System log. Ids were checked against the
# providers' own definitions on Windows (docs/verified-facts.md).
$script:EventQueries = @(
    @{ Provider = 'Microsoft-Windows-WHEA-Logger'; Ids = $null }
    @{ Provider = 'Microsoft-Windows-Kernel-Power'; Ids = @(41, 86) }
    @{ Provider = 'Microsoft-Windows-WER-SystemErrorReporting'; Ids = @(1000, 1001, 1006, 1019) }
    @{ Provider = 'Microsoft-Windows-MemoryDiagnostics-Results'; Ids = @(1101, 1102, 1201, 1202) }
    @{ Provider = 'Microsoft-Windows-Kernel-Processor-Power'; Ids = @(37) }
    @{ Provider = 'disk'; Ids = @(7, 11, 51, 52, 153) }
    @{ Provider = 'storahci'; Ids = @(129) }
    @{ Provider = 'stornvme'; Ids = @(11, 129) }
    @{ Provider = 'Ntfs'; Ids = @(55) }
    @{ Provider = 'Microsoft-Windows-Ntfs'; Ids = @(55) }
    @{ Provider = 'Display'; Ids = @(4101) }
)

# The only event data fields kept. Anything else in an event is dropped.
$script:EventDataKept = @(
    'BugcheckCode', 'BugcheckParameter1', 'BugcheckParameter2', 'BugcheckParameter3',
    'BugcheckParameter4', 'SleepInProgress', 'PowerButtonTimestamp',
    'LongPowerButtonPressDetected', 'BootAppStatus', 'param1', 'SuspectedDriver'
)

function Get-PCDoctorCollectorVersion { $script:CollectorVersion }
function Get-PCDoctorSchemaVersion { $script:SchemaVersion }
function Get-PCDoctorSensorColumns { , $script:SensorColumns }

function Test-PCDoctorAdmin {
    try {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($identity)
        return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch { return $false }
}

function ConvertTo-PCDoctorIsoTime {
    # UTC, ISO 8601, to the second. Null in, null out.
    param($Time)
    if ($null -eq $Time) { return $null }
    try { return ([datetime]$Time).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ', $script:Invariant) }
    catch { return $null }
}

function Protect-PCDoctorText {
    # Remove anything that could identify a person from text read out of
    # Windows (event messages), and cap its length. Belt and braces: the events
    # collected are hardware events, which should not contain such text at all.
    param([string]$Text, [int]$MaxLength = 600)
    if ([string]::IsNullOrEmpty($Text)) { return '' }
    $clean = $Text -replace '(?i)([A-Z]:\\Users\\)[^\\\s"]+', '$1<user>'
    $clean = $clean -replace '(?i)(serial\s*(?:number|no\.?)?\s*[:=]\s*)\S+', '$1<removed>'
    if ($env:COMPUTERNAME -and $env:COMPUTERNAME.Length -ge 3) {
        $clean = $clean -replace ('(?i)' + [regex]::Escape($env:COMPUTERNAME)), '<computer>'
    }
    if ($env:USERNAME -and $env:USERNAME.Length -ge 3) {
        $clean = $clean -replace ('(?i)\b' + [regex]::Escape($env:USERNAME) + '\b'), '<user>'
    }
    $clean = $clean.Trim()
    if ($clean.Length -gt $MaxLength) { $clean = $clean.Substring(0, $MaxLength) }
    return $clean
}

function Write-PCDoctorJson {
    # UTF-8 without a byte-order mark, the same on PowerShell 5.1 and 7.
    param($Object, [string]$Path)
    $json = ConvertTo-Json -InputObject $Object -Depth 8
    [System.IO.File]::WriteAllText($Path, $json, (New-Object System.Text.UTF8Encoding($false)))
}

function Get-PCDoctorCim {
    # Get-CimInstance that returns nothing instead of failing.
    param([string]$ClassName, [string]$Namespace = 'root/cimv2', [string]$Filter)
    try {
        if ($Filter) {
            return @(Get-CimInstance -ClassName $ClassName -Namespace $Namespace -Filter $Filter -ErrorAction Stop)
        }
        return @(Get-CimInstance -ClassName $ClassName -Namespace $Namespace -ErrorAction Stop)
    } catch { return @() }
}

function Get-PCDoctorTrimmed {
    param($Value)
    if ($null -eq $Value) { return $null }
    $text = ([string]$Value).Trim()
    if ($text.Length -eq 0) { return $null }
    return $text
}

# ------------------------------------------------------------------ specs

function Get-PCDoctorSystemType {
    param($ComputerSystem, $ChassisTypes)
    # Chassis types 8-14, 18, 21, 30-32 are portable machines (SMBIOS).
    $laptopChassis = @(8, 9, 10, 11, 12, 14, 18, 21, 30, 31, 32)
    foreach ($type in @($ChassisTypes)) {
        if ($laptopChassis -contains [int]$type) { return 'laptop' }
    }
    $pcType = 0
    if ($ComputerSystem -and $null -ne $ComputerSystem.PCSystemType) { $pcType = [int]$ComputerSystem.PCSystemType }
    switch ($pcType) {
        2 { return 'laptop' }
        4 { return 'server' }
        5 { return 'server' }
        7 { return 'server' }
        default { return 'desktop' }
    }
}

function Get-PCDoctorMemoryType {
    param($SmbiosMemoryType)
    # SMBIOS memory device type codes.
    $names = @{ 20 = 'DDR'; 21 = 'DDR2'; 24 = 'DDR3'; 26 = 'DDR4'; 27 = 'LPDDR'; 28 = 'LPDDR2'
        29 = 'LPDDR3'; 30 = 'LPDDR4'; 34 = 'DDR5'; 35 = 'LPDDR5' }
    if ($null -eq $SmbiosMemoryType) { return $null }
    $code = [int]$SmbiosMemoryType
    if ($names.ContainsKey($code)) { return $names[$code] }
    return $null
}

function Get-PCDoctorVramByAdapter {
    # Win32_VideoController.AdapterRAM is a 32-bit number and tops out at 4 GB.
    # The driver's registry key holds the real size.
    $result = @{}
    $key = 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}'
    try {
        foreach ($sub in @(Get-ChildItem -Path $key -ErrorAction SilentlyContinue)) {
            $props = Get-ItemProperty -Path $sub.PSPath -ErrorAction SilentlyContinue
            if (-not $props -or -not $props.DriverDesc) { continue }
            $size = $props.'HardwareInformation.qwMemorySize'
            if ($null -ne $size -and [int64]$size -gt 0) { $result[[string]$props.DriverDesc] = [int64]$size }
        }
    } catch { }
    return $result
}

function Get-PCDoctorPowerPlan {
    # "Power Scheme GUID: 381b4222-...  (Balanced)". The words are translated on
    # a non-English Windows; the GUID and the brackets are not.
    try {
        $line = (& powercfg.exe /getactivescheme 2>$null | Out-String)
        if ($line -match '([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\s*(?:\((.*)\))?') {
            return @{ guid = $Matches[1].ToLowerInvariant(); name = (Get-PCDoctorTrimmed $Matches[2]) }
        }
    } catch { }
    return @{ guid = $null; name = $null }
}

function Get-PCDoctorBattery {
    $static = Get-PCDoctorCim -ClassName 'BatteryStaticData' -Namespace 'root/wmi'
    $full = Get-PCDoctorCim -ClassName 'BatteryFullChargedCapacity' -Namespace 'root/wmi'
    if ($static.Count -eq 0 -or $full.Count -eq 0) { return $null }
    $design = [int64]$static[0].DesignedCapacity
    $capacity = [int64]$full[0].FullChargedCapacity
    if ($design -le 0) { return $null }
    $cycles = $null
    $cycleData = Get-PCDoctorCim -ClassName 'BatteryCycleCount' -Namespace 'root/wmi'
    if ($cycleData.Count -gt 0 -and [int]$cycleData[0].CycleCount -gt 0) { $cycles = [int]$cycleData[0].CycleCount }
    return [ordered]@{
        design_capacity_mwh      = $design
        full_charge_capacity_mwh = $capacity
        cycle_count              = $cycles
    }
}

function ConvertTo-PCDoctorMemoryModule {
    # One Win32_PhysicalMemory object -> one entry of memory.modules[].
    # SerialNumber is deliberately never read.
    param($Module)
    $capacity = [int64]0
    if ($Module.Capacity) { $capacity = [int64]$Module.Capacity }
    $form = $null
    if ($Module.FormFactor -eq 8) { $form = 'DIMM' } elseif ($Module.FormFactor -eq 12) { $form = 'SODIMM' }
    # BankLabel names the channel on boards where every DeviceLocator reads
    # the same (e.g. "P0 CHANNEL A" on AMD AM5). Scrubbed and capped like
    # any other text read from Windows.
    $bank = (Protect-PCDoctorText -Text ([string]$Module.BankLabel) -MaxLength 40).Trim()
    if ($bank.Length -eq 0) { $bank = $null }
    return [ordered]@{
        slot                 = Get-PCDoctorTrimmed $Module.DeviceLocator
        capacity_bytes       = $capacity
        speed_mhz            = $Module.Speed
        configured_speed_mhz = $Module.ConfiguredClockSpeed
        manufacturer         = Get-PCDoctorTrimmed $Module.Manufacturer
        part_number          = Get-PCDoctorTrimmed $Module.PartNumber
        type                 = Get-PCDoctorMemoryType $Module.SMBIOSMemoryType
        form_factor          = $form
        bank                 = $bank
    }
}

# The display modes Windows offers, read through user32's EnumDisplaySettings:
# a 360 Hz monitor left at 60 Hz shows up as "current 59, offered 360". Only
# mode numbers and the adapter's name are read. C#, because a screen has
# hundreds of modes and a PowerShell loop over P/Invoke is slow.
$script:DisplayModeSource = @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public static class PCDoctorDisplayModes {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct DISPLAY_DEVICE {
        public int cb;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string DeviceName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceString;
        public int StateFlags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceID;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceKey;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct DEVMODE {
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmDeviceName;
        public short dmSpecVersion, dmDriverVersion, dmSize, dmDriverExtra;
        public int dmFields;
        public int dmPositionX, dmPositionY, dmDisplayOrientation, dmDisplayFixedOutput;
        public short dmColor, dmDuplex, dmYResolution, dmTTOption, dmCollate;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmFormName;
        public short dmLogPixels;
        public int dmBitsPerPel, dmPelsWidth, dmPelsHeight, dmDisplayFlags, dmDisplayFrequency;
        public int dmICMMethod, dmICMIntent, dmMediaType, dmDitherType, dmReserved1, dmReserved2;
        public int dmPanningWidth, dmPanningHeight;
    }

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern bool EnumDisplayDevicesW(string device, uint index, ref DISPLAY_DEVICE info, uint flags);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern bool EnumDisplaySettingsW(string device, int mode, ref DEVMODE info);

    const int ENUM_CURRENT_SETTINGS = -1;
    const int ATTACHED_TO_DESKTOP = 0x1;
    const int MIRRORING_DRIVER = 0x8;
    const uint GET_DEVICE_INTERFACE_NAME = 0x1;

    public class Display {
        public string Adapter;
        public int Width, Height, Refresh, MaxAtResolution, Max;
        public string MonitorInterface;   // matches the monitor's WMI instance; not stored
    }

    static DISPLAY_DEVICE NewDevice() { var d = new DISPLAY_DEVICE(); d.cb = Marshal.SizeOf(typeof(DISPLAY_DEVICE)); return d; }
    static DEVMODE NewMode() { var m = new DEVMODE(); m.dmSize = (short)Marshal.SizeOf(typeof(DEVMODE)); return m; }

    public static List<Display> Read() {
        var result = new List<Display>();
        for (uint i = 0; i < 32; i++) {
            var adapter = NewDevice();
            if (!EnumDisplayDevicesW(null, i, ref adapter, 0)) break;
            if ((adapter.StateFlags & ATTACHED_TO_DESKTOP) == 0 || (adapter.StateFlags & MIRRORING_DRIVER) != 0) continue;
            var current = NewMode();
            if (!EnumDisplaySettingsW(adapter.DeviceName, ENUM_CURRENT_SETTINGS, ref current)) continue;
            var display = new Display();
            display.Adapter = adapter.DeviceString;
            display.Width = current.dmPelsWidth;
            display.Height = current.dmPelsHeight;
            display.Refresh = current.dmDisplayFrequency;
            for (int n = 0; n < 4096; n++) {
                var mode = NewMode();
                if (!EnumDisplaySettingsW(adapter.DeviceName, n, ref mode)) break;
                if (mode.dmDisplayFrequency <= 1) continue;   // 0 and 1 mean "the hardware's default"
                if (mode.dmDisplayFrequency > display.Max) display.Max = mode.dmDisplayFrequency;
                if (mode.dmPelsWidth == current.dmPelsWidth && mode.dmPelsHeight == current.dmPelsHeight &&
                    mode.dmDisplayFrequency > display.MaxAtResolution) display.MaxAtResolution = mode.dmDisplayFrequency;
            }
            var monitor = NewDevice();
            if (EnumDisplayDevicesW(adapter.DeviceName, 0, ref monitor, GET_DEVICE_INTERFACE_NAME)) display.MonitorInterface = monitor.DeviceID;
            result.Add(display);
        }
        return result;
    }
}
'@

function ConvertTo-PCDoctorMonitorKey {
    # A monitor's device interface name and its WMI instance name, brought to
    # one form so the two can be matched:
    #   \\?\DISPLAY#GSM5B7F#5&2b8f1c7&0&UID4352#{e6f07b5f-...}  -> DISPLAY\GSM5B7F\5&2B8F1C7&0&UID4352
    #   DISPLAY\GSM5B7F\5&2b8f1c7&0&UID4352_0                   -> DISPLAY\GSM5B7F\5&2B8F1C7&0&UID4352
    param([string]$Name)
    if (-not $Name) { return $null }
    $key = $Name.Trim()
    if ($key -match '^\\\\\?\\(.+?)#\{[0-9A-Fa-f-]+\}$') { $key = $Matches[1] -replace '#', '\' }
    $key = $key -replace '_\d+$', ''
    return $key.ToUpperInvariant()
}

function ConvertFrom-PCDoctorWmiString {
    # WMI gives a monitor's EDID strings as arrays of character codes, padded with zeros.
    param($Codes)
    if ($null -eq $Codes) { return $null }
    $chars = foreach ($code in @($Codes)) { if ([int]$code -gt 0) { [char][int]$code } }
    return Get-PCDoctorTrimmed (-join $chars)
}

function Get-PCDoctorMonitors {
    # Each monitor's model name and the highest refresh rate its EDID lists,
    # keyed by ConvertTo-PCDoctorMonitorKey. The serial number in the EDID is
    # never read.
    $monitors = @{}
    foreach ($id in (Get-PCDoctorCim -Namespace 'root/wmi' -ClassName 'WmiMonitorID')) {
        $key = ConvertTo-PCDoctorMonitorKey $id.InstanceName
        if (-not $key) { continue }
        $monitors[$key] = [ordered]@{ name = (Protect-PCDoctorText -Text (ConvertFrom-PCDoctorWmiString $id.UserFriendlyName) -MaxLength 64); max_refresh_hz = $null }
    }
    foreach ($modes in (Get-PCDoctorCim -Namespace 'root/wmi' -ClassName 'WmiMonitorListedSupportedSourceModes')) {
        $key = ConvertTo-PCDoctorMonitorKey $modes.InstanceName
        if (-not $key) { continue }
        $best = $null
        foreach ($mode in @($modes.MonitorSourceModes)) {
            if ($mode.VerticalRefreshRateDenominator -gt 0) {
                $hz = [math]::Round([double]$mode.VerticalRefreshRateNumerator / [double]$mode.VerticalRefreshRateDenominator)
                if ($null -eq $best -or $hz -gt $best) { $best = $hz }
            }
        }
        if (-not $monitors.ContainsKey($key)) { $monitors[$key] = [ordered]@{ name = $null; max_refresh_hz = $null } }
        $monitors[$key].max_refresh_hz = $best
    }
    return $monitors
}

function ConvertTo-PCDoctorDisplays {
    # Screens (from EnumDisplaySettings) joined with their monitors (from WMI).
    # With one screen and one monitor they belong together even when the two
    # names cannot be matched.
    param([object[]]$Screens, [hashtable]$Monitors)
    $result = @()
    $screenList = @($Screens | Where-Object { $_ })
    foreach ($screen in $screenList) {
        $monitor = $null
        $key = ConvertTo-PCDoctorMonitorKey $screen.MonitorInterface
        if ($key -and $Monitors -and $Monitors.ContainsKey($key)) { $monitor = $Monitors[$key] }
        elseif ($screenList.Count -eq 1 -and $Monitors -and $Monitors.Count -eq 1) { $monitor = @($Monitors.Values)[0] }
        $result += [ordered]@{
            adapter                      = Get-PCDoctorTrimmed $screen.Adapter
            resolution                   = $(if ($screen.Width -gt 0 -and $screen.Height -gt 0) { '{0}x{1}' -f $screen.Width, $screen.Height })
            refresh_hz                   = $(if ($screen.Refresh -gt 1) { [int]$screen.Refresh })
            max_refresh_hz_at_resolution = $(if ($screen.MaxAtResolution -gt 1) { [int]$screen.MaxAtResolution })
            max_refresh_hz               = $(if ($screen.Max -gt 1) { [int]$screen.Max })
            monitor                      = $(if ($monitor) { $monitor.name })
            monitor_max_refresh_hz       = $(if ($monitor -and $null -ne $monitor.max_refresh_hz) { [int]$monitor.max_refresh_hz })
        }
    }
    # Unrolled on purpose: callers wrap the answer in @(), which keeps an empty
    # or one-screen answer a list.
    return $result
}

function Get-PCDoctorDisplays {
    # Every screen attached to the desktop: what it runs at, and the most
    # Windows and the monitor offer. Empty when Windows answers nothing.
    $screens = @()
    try {
        if (-not ('PCDoctorDisplayModes' -as [type])) { Add-Type -TypeDefinition $script:DisplayModeSource -ErrorAction Stop }
        $screens = @([PCDoctorDisplayModes]::Read())
    } catch { return @() }
    return (ConvertTo-PCDoctorDisplays -Screens $screens -Monitors (Get-PCDoctorMonitors))
}

function Get-PCDoctorSpecs {
    # The parts in the PC and the Windows version. Deliberately NOT collected:
    # computer name, user names, serial numbers, MAC or IP addresses.
    $os = (Get-PCDoctorCim -ClassName 'Win32_OperatingSystem') | Select-Object -First 1
    $system = (Get-PCDoctorCim -ClassName 'Win32_ComputerSystem') | Select-Object -First 1
    $enclosure = (Get-PCDoctorCim -ClassName 'Win32_SystemEnclosure') | Select-Object -First 1
    $board = (Get-PCDoctorCim -ClassName 'Win32_BaseBoard') | Select-Object -First 1
    $bios = (Get-PCDoctorCim -ClassName 'Win32_BIOS') | Select-Object -First 1

    $osInfo = $null
    if ($os) {
        $uptime = $null
        if ($os.LastBootUpTime) { $uptime = [math]::Round(((Get-Date) - $os.LastBootUpTime).TotalHours, 1) }
        $osInfo = [ordered]@{
            caption      = Get-PCDoctorTrimmed $os.Caption
            version      = Get-PCDoctorTrimmed $os.Version
            build        = Get-PCDoctorTrimmed $os.BuildNumber
            architecture = Get-PCDoctorTrimmed $os.OSArchitecture
            last_boot    = ConvertTo-PCDoctorIsoTime $os.LastBootUpTime
            uptime_hours = $uptime
        }
    }

    $chassis = @()
    if ($enclosure -and $enclosure.ChassisTypes) { $chassis = @($enclosure.ChassisTypes) }
    $systemInfo = [ordered]@{
        manufacturer = $(if ($system) { Get-PCDoctorTrimmed $system.Manufacturer })
        model        = $(if ($system) { Get-PCDoctorTrimmed $system.Model })
        type         = Get-PCDoctorSystemType -ComputerSystem $system -ChassisTypes $chassis
    }

    $cpus = @()
    foreach ($cpu in (Get-PCDoctorCim -ClassName 'Win32_Processor')) {
        $cpus += [ordered]@{
            name          = Get-PCDoctorTrimmed $cpu.Name
            manufacturer  = Get-PCDoctorTrimmed $cpu.Manufacturer
            cores         = $cpu.NumberOfCores
            threads       = $cpu.NumberOfLogicalProcessors
            max_clock_mhz = $cpu.MaxClockSpeed
        }
    }

    $vram = Get-PCDoctorVramByAdapter
    $gpus = @()
    foreach ($gpu in (Get-PCDoctorCim -ClassName 'Win32_VideoController')) {
        $name = Get-PCDoctorTrimmed $gpu.Name
        if (-not $name) { continue }
        $memory = $null
        if ($vram.ContainsKey($name)) { $memory = $vram[$name] }
        elseif ($gpu.AdapterRAM) { $memory = [int64]$gpu.AdapterRAM }
        $resolution = $null
        if ($gpu.CurrentHorizontalResolution -and $gpu.CurrentVerticalResolution) {
            $resolution = '{0}x{1}' -f $gpu.CurrentHorizontalResolution, $gpu.CurrentVerticalResolution
        }
        $gpus += [ordered]@{
            name           = $name
            driver_version = Get-PCDoctorTrimmed $gpu.DriverVersion
            driver_date    = ConvertTo-PCDoctorIsoTime $gpu.DriverDate
            vram_bytes     = $memory
            resolution     = $resolution
            refresh_hz     = $gpu.CurrentRefreshRate
        }
    }

    $modules = @()
    $totalMemory = [int64]0
    foreach ($stick in (Get-PCDoctorCim -ClassName 'Win32_PhysicalMemory')) {
        $module = ConvertTo-PCDoctorMemoryModule -Module $stick
        $totalMemory += $module['capacity_bytes']
        $modules += $module
    }
    if ($totalMemory -le 0 -and $system -and $system.TotalPhysicalMemory) { $totalMemory = [int64]$system.TotalPhysicalMemory }
    $slots = 0
    foreach ($array in (Get-PCDoctorCim -ClassName 'Win32_PhysicalMemoryArray')) {
        if ($array.MemoryDevices) { $slots += [int]$array.MemoryDevices }
    }

    $plan = Get-PCDoctorPowerPlan
    return [ordered]@{
        os              = $osInfo
        system          = $systemInfo
        cpu             = @($cpus)
        gpu             = @($gpus)
        displays        = @(Get-PCDoctorDisplays)
        memory          = [ordered]@{
            total_bytes = $totalMemory
            slots_total = $(if ($slots -gt 0) { $slots } else { $null })
            modules     = @($modules)
        }
        motherboard     = [ordered]@{
            manufacturer = $(if ($board) { Get-PCDoctorTrimmed $board.Manufacturer })
            product      = $(if ($board) { Get-PCDoctorTrimmed $board.Product })
            version      = $(if ($board) { Get-PCDoctorTrimmed $board.Version })
        }
        bios            = [ordered]@{
            vendor       = $(if ($bios) { Get-PCDoctorTrimmed $bios.Manufacturer })
            version      = $(if ($bios) { Get-PCDoctorTrimmed $bios.SMBIOSBIOSVersion })
            release_date = $(if ($bios) { ConvertTo-PCDoctorIsoTime $bios.ReleaseDate })
        }
        power_plan      = $plan.name
        power_plan_guid = $plan.guid
        battery         = Get-PCDoctorBattery
    }
}

# ----------------------------------------------------------------- events

function Get-PCDoctorLevelName {
    # By number, so it is the same on every language of Windows.
    param($Level)
    switch ([int]$Level) {
        1 { 'Critical' }
        2 { 'Error' }
        3 { 'Warning' }
        default { 'Information' }
    }
}

function ConvertTo-PCDoctorEvent {
    # One event log record -> the small object that is saved.
    param($Record)
    $data = @{}
    try {
        $xml = [xml]$Record.ToXml()
        foreach ($item in @($xml.Event.EventData.Data)) {
            if ($null -eq $item) { continue }
            $name = $null
            try { $name = $item.Name } catch { }
            if ($name -and ($script:EventDataKept -contains $name)) {
                $data[[string]$name] = Protect-PCDoctorText -Text ([string]$item.'#text') -MaxLength 200
            }
        }
    } catch { }
    $message = ''
    try { $message = Protect-PCDoctorText -Text ([string]$Record.Message) } catch { }
    return [ordered]@{
        time     = ConvertTo-PCDoctorIsoTime $Record.TimeCreated
        provider = [string]$Record.ProviderName
        id       = [int]$Record.Id
        level    = Get-PCDoctorLevelName $Record.Level
        log      = [string]$Record.LogName
        message  = $message
        data     = $data
    }
}

function Get-PCDoctorEvents {
    # Hardware-related events from the System log for the last $Days days.
    # Only the providers and ids in $script:EventQueries are read.
    param([int]$Days = 30, [int]$MaxPerQuery = 200)
    $start = (Get-Date).AddDays(-$Days)
    $events = New-Object System.Collections.Generic.List[object]
    $errors = New-Object System.Collections.Generic.List[string]
    foreach ($query in $script:EventQueries) {
        $filter = @{ LogName = 'System'; ProviderName = $query.Provider; StartTime = $start }
        if ($query.Ids) { $filter['Id'] = $query.Ids }
        try {
            $found = @(Get-WinEvent -FilterHashtable $filter -MaxEvents $MaxPerQuery -ErrorAction Stop)
            foreach ($record in $found) { $events.Add((ConvertTo-PCDoctorEvent $record)) }
            if ($found.Count -ge $MaxPerQuery) {
                $errors.Add("More than $MaxPerQuery events from $($query.Provider); only the newest $MaxPerQuery were kept.")
            }
        } catch {
            # "No events found" and "this PC has no such provider" are the normal,
            # healthy answers. Anything else is worth telling the technician.
            $id = [string]$_.FullyQualifiedErrorId
            $text = [string]$_.Exception.Message
            $benign = ($id -like 'NoMatchingEventsFound*') -or ($id -like 'NoMatchingProvidersFound*') -or
                ($id -like 'ProviderNotFound*') -or ($text -match '(?i)no events were found|not an event provider|do not write events|could not be found')
            if (-not $benign) { $errors.Add("Could not read $($query.Provider) events: $text") }
        }
    }
    $sorted = @($events | Sort-Object { $_.time })
    return [ordered]@{
        window_days  = $Days
        collected_at = ConvertTo-PCDoctorIsoTime (Get-Date)
        events       = $sorted
        errors       = @($errors)
    }
}

function Get-PCDoctorEventSummary {
    # Plain counts for the console, so the technician sees red flags at once
    # even with no dashboard to hand. The real diagnosis is done by the analyzer.
    param($EventDocument)
    $events = @($EventDocument.events)
    $whea = @($events | Where-Object { $_.provider -eq 'Microsoft-Windows-WHEA-Logger' -and $_.id -ne 3 })
    $power = @($events | Where-Object { $_.provider -eq 'Microsoft-Windows-Kernel-Power' -and $_.id -eq 41 })
    $thermal = @($events | Where-Object { $_.provider -eq 'Microsoft-Windows-Kernel-Power' -and $_.id -eq 86 })
    $bugchecks = @($events | Where-Object { $_.provider -eq 'Microsoft-Windows-WER-SystemErrorReporting' -and $_.id -ne 1019 })
    $codes = @()
    foreach ($crash in $bugchecks) {
        $text = [string]$crash.data['param1']
        if (-not $text) { $text = [string]$crash.message }
        if ($text -match '(0x[0-9A-Fa-f]{8})') { $codes += $Matches[1].ToLowerInvariant() }
    }
    $disk = @($events | Where-Object { @('disk', 'storahci', 'stornvme', 'Ntfs', 'Microsoft-Windows-Ntfs') -contains $_.provider })
    $display = @($events | Where-Object { $_.provider -eq 'Display' })
    $memory = @($events | Where-Object { $_.provider -eq 'Microsoft-Windows-MemoryDiagnostics-Results' -and @(1102, 1202) -contains $_.id })
    return [ordered]@{
        whea_errors          = $whea.Count
        unexpected_shutdowns = $power.Count
        thermal_shutdowns    = $thermal.Count
        blue_screens         = $bugchecks.Count
        stop_codes           = @($codes | Sort-Object -Unique)
        disk_errors          = $disk.Count
        display_resets       = $display.Count
        memory_test_failures = $memory.Count
    }
}

# ------------------------------------------------------------------ disks

function Get-PCDoctorNumberOrNull {
    param($Value)
    if ($null -eq $Value) { return $null }
    try { return [int64]$Value } catch { return $null }
}

function ConvertTo-PCDoctorDiskNumber {
    # Get-PhysicalDisk's DeviceId is the Windows disk number as text ("3"),
    # the "Disk 3" that disk events name. Anything else -> $null.
    param($Value)
    if ($null -eq $Value) { return $null }
    $number = 0
    $styles = [System.Globalization.NumberStyles]::Integer
    if (-not [int]::TryParse(([string]$Value).Trim(), $styles, $script:Invariant, [ref]$number)) { return $null }
    if ($number -lt 0) { return $null }
    return $number
}

function ConvertTo-PCDoctorPhysicalDisk {
    # One Get-PhysicalDisk object -> one entry of physical_disks[].
    # SerialNumber is deliberately never read.
    param($Disk, $Reliability)
    return [ordered]@{
        name               = Get-PCDoctorTrimmed $Disk.FriendlyName
        media_type         = [string]$Disk.MediaType
        bus_type           = [string]$Disk.BusType
        health_status      = [string]$Disk.HealthStatus
        operational_status = (@($Disk.OperationalStatus) -join ', ')
        size_bytes         = Get-PCDoctorNumberOrNull $Disk.Size
        firmware           = Get-PCDoctorTrimmed $Disk.FirmwareVersion
        reliability        = $Reliability
        number             = ConvertTo-PCDoctorDiskNumber $Disk.DeviceId
    }
}

function Get-PCDoctorDisks {
    # Disk health as Windows reports it. Serial numbers and volume labels are
    # deliberately left out.
    $warnings = New-Object System.Collections.Generic.List[string]
    $physical = @()
    $disks = @()
    try { $disks = @(Get-PhysicalDisk -ErrorAction Stop) }
    catch { $warnings.Add("Could not list physical disks: $($_.Exception.Message)") }
    $reliabilityFailed = $false
    foreach ($disk in $disks) {
        $reliability = $null
        try {
            $counter = $disk | Get-StorageReliabilityCounter -ErrorAction Stop
            if ($counter) {
                $reliability = [ordered]@{
                    temperature_c            = Get-PCDoctorNumberOrNull $counter.Temperature
                    temperature_max_c        = Get-PCDoctorNumberOrNull $counter.TemperatureMax
                    wear_pct                 = Get-PCDoctorNumberOrNull $counter.Wear
                    read_errors_total        = Get-PCDoctorNumberOrNull $counter.ReadErrorsTotal
                    read_errors_uncorrected  = Get-PCDoctorNumberOrNull $counter.ReadErrorsUncorrected
                    write_errors_total       = Get-PCDoctorNumberOrNull $counter.WriteErrorsTotal
                    write_errors_uncorrected = Get-PCDoctorNumberOrNull $counter.WriteErrorsUncorrected
                    power_on_hours           = Get-PCDoctorNumberOrNull $counter.PowerOnHours
                    start_stop_cycles        = Get-PCDoctorNumberOrNull $counter.StartStopCycleCount
                }
            }
        } catch { $reliabilityFailed = $true }
        $physical += ConvertTo-PCDoctorPhysicalDisk -Disk $disk -Reliability $reliability
    }
    if ($reliabilityFailed) {
        $warnings.Add('Disk wear, temperature and error counters could not be read (this needs administrator rights).')
    }

    $volumes = @()
    $systemLetter = ''
    if ($env:SystemDrive) { $systemLetter = $env:SystemDrive.Substring(0, 1).ToUpperInvariant() }
    try {
        foreach ($volume in @(Get-Volume -ErrorAction Stop)) {
            if (-not $volume.DriveLetter) { continue }
            if ([string]$volume.DriveType -ne 'Fixed') { continue }
            $letter = ([string]$volume.DriveLetter).ToUpperInvariant()
            $volumes += [ordered]@{
                drive_letter  = $letter
                file_system   = Get-PCDoctorTrimmed $volume.FileSystem
                size_bytes    = Get-PCDoctorNumberOrNull $volume.Size
                free_bytes    = Get-PCDoctorNumberOrNull $volume.SizeRemaining
                health_status = [string]$volume.HealthStatus
                is_system     = ($letter -eq $systemLetter)
            }
        }
    } catch { $warnings.Add("Could not list volumes: $($_.Exception.Message)") }

    return [ordered]@{
        physical_disks = @($physical)
        volumes        = @($volumes)
        warnings       = @($warnings)
    }
}

# ---------------------------------------------------------------- sensors

function ConvertTo-PCDoctorNumber {
    # "45.0 C", "7,5 GB", 45.2 or $null -> a number (or $null).
    # Data sizes with a unit are returned in megabytes so two of them compare.
    param($Value)
    if ($null -eq $Value) { return $null }
    if ($Value -is [double] -or $Value -is [single] -or $Value -is [int] -or $Value -is [long] -or $Value -is [decimal]) {
        $number = [double]$Value
        if ([double]::IsNaN($number) -or [double]::IsInfinity($number)) { return $null }
        return $number
    }
    $text = ([string]$Value).Trim()
    if ($text -notmatch '(-?\d+(?:[.,]\d+)?)\s*([KMGT]B)?') { return $null }
    $number = [double]::Parse($Matches[1].Replace(',', '.'), $script:Invariant)
    switch ($Matches[2]) {
        'KB' { $number = $number / 1024 }
        'GB' { $number = $number * 1024 }
        'TB' { $number = $number * 1024 * 1024 }
    }
    return $number
}

function ConvertFrom-PCDoctorLhmTree {
    # Flatten LibreHardwareMonitor's data.json tree into a list of sensors.
    # Field names (SensorId, Type, Text, RawValue, Value, Children) were read
    # from LibreHardwareMonitor's HttpServer.cs.
    param($Node)
    $out = New-Object System.Collections.Generic.List[object]
    $stack = New-Object System.Collections.Stack
    $stack.Push($Node)
    while ($stack.Count -gt 0) {
        $current = $stack.Pop()
        if ($null -eq $current) { continue }
        $sensorId = $null
        try { $sensorId = $current.SensorId } catch { }
        if ($sensorId) {
            $raw = $null
            try { $raw = $current.RawValue } catch { }
            if ($null -eq $raw) { try { $raw = $current.Value } catch { } }
            $out.Add([pscustomobject]@{
                    SensorId = [string]$sensorId
                    Type     = [string]$current.Type
                    Text     = [string]$current.Text
                    Value    = ConvertTo-PCDoctorNumber $raw
                })
        }
        $children = $null
        try { $children = $current.Children } catch { }
        foreach ($child in @($children)) { if ($null -ne $child) { $stack.Push($child) } }
    }
    return , $out.ToArray()
}

function Select-PCDoctorGpuPrefix {
    # Which graphics adapter to follow: a graphics card before integrated
    # graphics. Decided once, on the first sample, so the columns never switch
    # adapters halfway through a run.
    param([object[]]$Sensors)
    $prefixes = @($Sensors | ForEach-Object { if ($_.SensorId -match '^(/gpu-[a-z-]+/\d+)/') { $Matches[1] } } | Sort-Object -Unique)
    if ($prefixes.Count -eq 0) { return $null }
    foreach ($kind in @('/gpu-nvidia/', '/gpu-amd/', '/gpu-intel/')) {
        $match = @($prefixes | Where-Object { $_.StartsWith($kind) })
        if ($match.Count -gt 0) { return $match[0] }
    }
    return $prefixes[0]
}

function Get-PCDoctorSensorValue {
    # The first sensor of a type whose name is one of $Names (in that order).
    param([object[]]$Sensors, [string]$Type, [string[]]$Names)
    foreach ($name in $Names) {
        foreach ($sensor in $Sensors) {
            if ($sensor.Type -eq $Type -and $sensor.Text -eq $name -and $null -ne $sensor.Value) { return $sensor.Value }
        }
    }
    return $null
}

function ConvertTo-PCDoctorSample {
    # LibreHardwareMonitor sensors -> one row of sensors.csv (a hashtable with
    # the fixed column names; a missing reading is $null).
    # Sensor names were read from LibreHardwareMonitor's source: IntelCpu.cs,
    # Amd17Cpu.cs, GenericCpu.cs, NvidiaGpu.cs, AmdGpu.cs, TotalMemory.cs.
    param([object[]]$Sensors, [string]$GpuPrefix)
    $sample = @{}
    foreach ($column in $script:SensorColumns) { $sample[$column] = $null }
    if (-not $Sensors -or $Sensors.Count -eq 0) { return $sample }

    $cpu = @($Sensors | Where-Object { $_.SensorId -match '^/(intelcpu|amdcpu)/0/' })
    if ($cpu.Count -gt 0) {
        $temp = Get-PCDoctorSensorValue $cpu 'Temperature' @('CPU Package', 'Core (Tctl/Tdie)', 'Core (Tdie)', 'Core (Tctl)', 'Core Max', 'CCDs Max (Tdie)', 'Core Average')
        if ($null -eq $temp) {
            $others = @($cpu | Where-Object { $_.Type -eq 'Temperature' -and $_.Text -notmatch 'Distance' -and $null -ne $_.Value } | ForEach-Object { $_.Value })
            if ($others.Count -gt 0) { $temp = ($others | Measure-Object -Maximum).Maximum }
        }
        $sample['cpu_temp_c'] = $temp
        $sample['cpu_load_pct'] = Get-PCDoctorSensorValue $cpu 'Load' @('CPU Total')
        $coreMax = Get-PCDoctorSensorValue $cpu 'Load' @('CPU Core Max')
        if ($null -eq $coreMax) {
            $loads = @($cpu | Where-Object { $_.Type -eq 'Load' -and $_.Text -match 'Core #\d+' -and $null -ne $_.Value } | ForEach-Object { $_.Value })
            if ($loads.Count -gt 0) { $coreMax = ($loads | Measure-Object -Maximum).Maximum }
        }
        $sample['cpu_core_max_load_pct'] = $coreMax
        $clock = Get-PCDoctorSensorValue $cpu 'Clock' @('Cores (Average)')
        if ($null -eq $clock) {
            $clocks = @($cpu | Where-Object { $_.Type -eq 'Clock' -and $_.Text -match 'Core #\d+$' -and $null -ne $_.Value } | ForEach-Object { $_.Value })
            if ($clocks.Count -gt 0) { $clock = ($clocks | Measure-Object -Average).Average }
        }
        $sample['cpu_clock_mhz'] = $clock
        $sample['cpu_power_w'] = Get-PCDoctorSensorValue $cpu 'Power' @('CPU Package', 'Package')
    }

    if (-not $GpuPrefix) { $GpuPrefix = Select-PCDoctorGpuPrefix $Sensors }
    if ($GpuPrefix) {
        $gpu = @($Sensors | Where-Object { $_.SensorId.StartsWith($GpuPrefix + '/') })
        $sample['gpu_temp_c'] = Get-PCDoctorSensorValue $gpu 'Temperature' @('GPU Core')
        $sample['gpu_hotspot_c'] = Get-PCDoctorSensorValue $gpu 'Temperature' @('GPU Hot Spot')
        $sample['gpu_load_pct'] = Get-PCDoctorSensorValue $gpu 'Load' @('GPU Core', 'D3D 3D')
        $sample['gpu_clock_mhz'] = Get-PCDoctorSensorValue $gpu 'Clock' @('GPU Core')
        $sample['gpu_power_w'] = Get-PCDoctorSensorValue $gpu 'Power' @('GPU Package', 'GPU Power', 'GPU Core')
        $fans = @($gpu | Where-Object { $_.Type -eq 'Fan' -and $null -ne $_.Value })
        if ($fans.Count -gt 0) { $sample['gpu_fan_rpm'] = $fans[0].Value }
        # Used / total is a ratio, so it does not matter which unit the
        # LibreHardwareMonitor version reports data sizes in.
        $used = $null
        $total = $null
        foreach ($type in @('SmallData', 'Data')) {
            if ($null -eq $used) { $used = Get-PCDoctorSensorValue $gpu $type @('GPU Memory Used') }
            if ($null -eq $total) { $total = Get-PCDoctorSensorValue $gpu $type @('GPU Memory Total') }
        }
        if ($null -ne $used -and $null -ne $total -and $total -gt 0) {
            $sample['gpu_vram_used_pct'] = [math]::Min(100.0, 100.0 * $used / $total)
        } else {
            $sample['gpu_vram_used_pct'] = Get-PCDoctorSensorValue $gpu 'Load' @('GPU Memory')
        }
    }

    $ram = @($Sensors | Where-Object { $_.SensorId -match '^/ram/' })
    if ($ram.Count -gt 0) { $sample['ram_used_pct'] = Get-PCDoctorSensorValue $ram 'Load' @('Memory') }
    return $sample
}

function Get-PCDoctorLhmSensors {
    # Read LibreHardwareMonitor's built-in web server. Returns $null when it is
    # not running or its "Remote Web Server" option is off (the default).
    param([string]$Url = 'http://localhost:8085', [int]$TimeoutSec = 2)
    try {
        $tree = Invoke-RestMethod -Uri ($Url.TrimEnd('/') + '/data.json') -TimeoutSec $TimeoutSec -ErrorAction Stop
        $sensors = ConvertFrom-PCDoctorLhmTree $tree
        if ($sensors.Count -eq 0) { return $null }
        return $sensors
    } catch { return $null }
}

# Each graphics adapter's temperature and fan speed as Windows' own graphics
# kernel reports them (D3DKMTQueryAdapterInfo, KMTQAITYPE_ADAPTERPERFDATA, the
# source Task Manager shows; WDDM 2.4 or later). Needs no vendor tool, so it
# covers AMD and Intel cards. Only raw numbers are returned; the PowerShell
# side decides what counts as a reading. Never throws: on an old Windows, or
# outside Windows, the answer is just shorter or empty.
$script:GpuPerfSource = @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public static class PCDoctorGpuPerf {
    [StructLayout(LayoutKind.Sequential)]
    struct D3DKMT_ENUMADAPTERS2 {
        public uint NumAdapters;
        public IntPtr pAdapters;          // D3DKMT_ADAPTERINFO[], 20 bytes each
    }

    [StructLayout(LayoutKind.Sequential)]
    struct D3DKMT_QUERYADAPTERINFO {
        public uint hAdapter;
        public int Type;
        public IntPtr pPrivateDriverData;
        public uint PrivateDriverDataSize;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct D3DKMT_CLOSEADAPTER {
        public uint hAdapter;
    }

    [DllImport("gdi32.dll")]
    static extern int D3DKMTEnumAdapters2(ref D3DKMT_ENUMADAPTERS2 info);
    [DllImport("gdi32.dll")]
    static extern int D3DKMTQueryAdapterInfo(ref D3DKMT_QUERYADAPTERINFO info);
    [DllImport("gdi32.dll")]
    static extern int D3DKMTCloseAdapter(ref D3DKMT_CLOSEADAPTER info);

    const int KMTQAITYPE_ADAPTERPERFDATA = 62;
    const int ADAPTERINFO_SIZE = 20;      // hAdapter, LUID (low, high), NumOfSources, BOOL
    const int PERFDATA_SIZE = 64;
    const int PERFDATA_FAN_RPM = 48;
    const int PERFDATA_TEMPERATURE = 56;  // deci-Celsius
    const int MAX_ADAPTERS = 64;

    public class Adapter {
        public uint LuidLow;
        public int LuidHigh;              // matches the GPU engine counters; not stored
        public int Status;                // NTSTATUS of the perfdata query, 0 = success
        public long TemperatureDeciC;     // raw; 0 = the driver gave none
        public long FanRpm;               // raw; 0 = the driver gave none
    }

    public static List<Adapter> Read() {
        var result = new List<Adapter>();
        var handles = new List<uint>();
        IntPtr list = IntPtr.Zero;
        try {
            var enumInfo = new D3DKMT_ENUMADAPTERS2();
            if (D3DKMTEnumAdapters2(ref enumInfo) != 0) return result;
            uint count = enumInfo.NumAdapters;
            if (count == 0 || count > MAX_ADAPTERS) return result;
            list = Marshal.AllocHGlobal((int)count * ADAPTERINFO_SIZE);
            for (int b = 0; b < (int)count * ADAPTERINFO_SIZE; b++) Marshal.WriteByte(list, b, 0);
            enumInfo.NumAdapters = count;
            enumInfo.pAdapters = list;
            if (D3DKMTEnumAdapters2(ref enumInfo) != 0) return result;
            uint filled = Math.Min(enumInfo.NumAdapters, count);
            for (int i = 0; i < (int)filled; i++) {
                int at = i * ADAPTERINFO_SIZE;
                uint handle = (uint)Marshal.ReadInt32(list, at);
                handles.Add(handle);
                var adapter = new Adapter();
                adapter.LuidLow = (uint)Marshal.ReadInt32(list, at + 4);
                adapter.LuidHigh = Marshal.ReadInt32(list, at + 8);
                adapter.Status = -1;
                IntPtr perf = IntPtr.Zero;
                try {
                    perf = Marshal.AllocHGlobal(PERFDATA_SIZE);
                    for (int b = 0; b < PERFDATA_SIZE; b++) Marshal.WriteByte(perf, b, 0);   // PhysicalAdapterIndex = 0
                    var query = new D3DKMT_QUERYADAPTERINFO();
                    query.hAdapter = handle;
                    query.Type = KMTQAITYPE_ADAPTERPERFDATA;
                    query.pPrivateDriverData = perf;
                    query.PrivateDriverDataSize = PERFDATA_SIZE;
                    adapter.Status = D3DKMTQueryAdapterInfo(ref query);
                    if (adapter.Status == 0) {
                        adapter.TemperatureDeciC = (uint)Marshal.ReadInt32(perf, PERFDATA_TEMPERATURE);
                        adapter.FanRpm = (uint)Marshal.ReadInt32(perf, PERFDATA_FAN_RPM);
                    }
                } catch (Exception) {
                } finally {
                    if (perf != IntPtr.Zero) Marshal.FreeHGlobal(perf);
                }
                result.Add(adapter);
            }
        } catch (Exception) {
        } finally {
            foreach (uint handle in handles) {
                try { var close = new D3DKMT_CLOSEADAPTER(); close.hAdapter = handle; D3DKMTCloseAdapter(ref close); } catch (Exception) { }
            }
            if (list != IntPtr.Zero) Marshal.FreeHGlobal(list);
        }
        return result;
    }
}
'@

function ConvertTo-PCDoctorGpuLuidKey {
    # One form for an adapter's LUID, as the GPU engine counters write it
    # (pid_1234_luid_0x00000000_0x0000D1A5_phys_0_eng_0_engtype_3D):
    # 0x{HighPart:X8}_0x{LowPart:X8}. Takes either the two parts or the
    # "0x..._0x..." text from a counter name. Used only for matching; never stored.
    param([object]$High, [object]$Low)
    if ($High -is [string] -and $null -eq $Low) {
        if ($High -notmatch '^(?:luid_)?0x([0-9A-Fa-f]{1,8})_0x([0-9A-Fa-f]{1,8})$') { return $null }
        $highPart = [Convert]::ToUInt32($Matches[1], 16)
        $lowPart = [Convert]::ToUInt32($Matches[2], 16)
    } else {
        if ($null -eq $High -or $null -eq $Low) { return $null }
        $highPart = [uint32]([int64]$High -band 0xFFFFFFFFL)
        $lowPart = [uint32]([int64]$Low -band 0xFFFFFFFFL)
    }
    return ('0x{0:X8}_0x{1:X8}' -f $highPart, $lowPart)
}

function ConvertTo-PCDoctorGpuPerfReading {
    # Raw D3DKMT numbers -> readings. A driver that does not fill a field gives
    # 0; a temperature over 150 C is not a real one either.
    param($Adapter)
    $reading = [ordered]@{ key = $null; temperature_c = $null; fan_rpm = $null }
    if ($null -eq $Adapter) { return $reading }
    $reading.key = ConvertTo-PCDoctorGpuLuidKey $Adapter.LuidHigh $Adapter.LuidLow
    if ($null -ne $Adapter.Status -and [int]$Adapter.Status -ne 0) { return $reading }
    $deci = [double]$Adapter.TemperatureDeciC
    if ($deci -gt 0 -and $deci -le 1500) { $reading.temperature_c = $deci / 10.0 }
    $fan = [double]$Adapter.FanRpm
    if ($fan -gt 0 -and $fan -lt 100000) { $reading.fan_rpm = $fan }
    return $reading
}

function Select-PCDoctorBusiestGpuKey {
    # The adapter with the highest 3D load, by LUID key. $null when there is
    # no clear one (no LUIDs in the counter names, or a tie - often all 0).
    param([hashtable]$LoadByAdapter)
    if (-not $LoadByAdapter -or $LoadByAdapter.Count -eq 0) { return $null }
    $best = $null
    $bestLoad = $null
    $tie = $false
    foreach ($key in $LoadByAdapter.Keys) {
        $load = [double]$LoadByAdapter[$key]
        if ($null -eq $bestLoad -or $load -gt $bestLoad) { $best = $key; $bestLoad = $load; $tie = $false }
        elseif ($load -eq $bestLoad) { $tie = $true }
    }
    if ($tie -or -not (ConvertTo-PCDoctorGpuLuidKey ([string]$best))) { return $null }
    return (ConvertTo-PCDoctorGpuLuidKey ([string]$best))
}

function Select-PCDoctorGpuPerfReading {
    # Which adapter's D3DKMT reading belongs in the sample: the busiest
    # adapter's, when it can be matched by LUID (even if it gave no
    # temperature - another adapter's would be the wrong GPU); otherwise the
    # one adapter that reports a temperature; otherwise none.
    param([object[]]$Readings, [string]$BusiestKey)
    $readings = @($Readings | Where-Object { $_ })
    if ($BusiestKey) {
        foreach ($reading in $readings) {
            if ($reading.key -and $reading.key -eq $BusiestKey) {
                if ($null -eq $reading.temperature_c -and $null -eq $reading.fan_rpm) { return $null }
                return $reading
            }
        }
    }
    $withTemperature = @($readings | Where-Object { $null -ne $_.temperature_c })
    if ($withTemperature.Count -eq 1) { return $withTemperature[0] }
    return $null
}

function Get-PCDoctorGpuPerf {
    # Every adapter's D3DKMT reading (see $script:GpuPerfSource). Empty when
    # Windows gives none. The C# is compiled once; if that fails it is not
    # tried again for every sample.
    if ($script:GpuPerfUnavailable) { return @() }
    try {
        if (-not ('PCDoctorGpuPerf' -as [type])) { Add-Type -TypeDefinition $script:GpuPerfSource -ErrorAction Stop }
        $adapters = @([PCDoctorGpuPerf]::Read())
    } catch {
        $script:GpuPerfUnavailable = $true
        return @()
    }
    $readings = foreach ($adapter in $adapters) { ConvertTo-PCDoctorGpuPerfReading $adapter }
    return @($readings)
}

function Find-PCDoctorNvidiaSmi {
    # The NVIDIA driver puts nvidia-smi in System32, which only administrators
    # can change, so look there first. The PATH is used only when not
    # elevated. Either way it must be signed by NVIDIA.
    param(
        [switch]$Elevated,
        [scriptblock]$IsTrusted = { param($file) Test-PCDoctorSignedBy -Path $file -Publisher 'NVIDIA Corporation' }
    )
    $candidates = @()
    if ($env:SystemRoot) {
        $system = Join-Path $env:SystemRoot 'System32\nvidia-smi.exe'
        if (Test-Path -LiteralPath $system -PathType Leaf) { $candidates += $system }
    }
    if (-not $Elevated) {
        $command = Get-Command 'nvidia-smi.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command) { $candidates += $command.Source }
    }
    foreach ($candidate in $candidates) {
        if (& $IsTrusted $candidate) { return $candidate }
    }
    return $null
}

function Get-PCDoctorWindowsSample {
    # Readings Windows can give without any extra tool: CPU load and speed, RAM
    # use, GPU load, and on AMD and Intel cards the GPU temperature (and fan)
    # from Windows' own adapter counters - and, with an NVIDIA card, its
    # temperature, power and memory from nvidia-smi. No CPU temperature: Windows has no reliable source
    # for it, which is why LibreHardwareMonitor is recommended.
    # CIM classes are used instead of Get-Counter because performance counter
    # names are translated on a non-English Windows and these are not.
    param([string]$NvidiaSmi)
    $sample = @{}
    foreach ($column in $script:SensorColumns) { $sample[$column] = $null }

    $processors = Get-PCDoctorCim -ClassName 'Win32_PerfFormattedData_Counters_ProcessorInformation'
    $coreMax = $null
    foreach ($item in $processors) {
        $load = $null
        if ($null -ne $item.PercentProcessorUtility) { $load = [double]$item.PercentProcessorUtility }
        elseif ($null -ne $item.PercentProcessorTime) { $load = [double]$item.PercentProcessorTime }
        if ($null -ne $load) { $load = [math]::Min(100.0, $load) }
        if ($item.Name -eq '_Total') {
            $sample['cpu_load_pct'] = $load
            if ($null -ne $item.PercentProcessorPerformance -and [double]$item.PercentProcessorPerformance -gt 0) {
                $sample['cpu_perf_pct'] = [double]$item.PercentProcessorPerformance
            }
            $frequency = $null
            try { $frequency = $item.ActualFrequency } catch { }
            if ($null -ne $frequency -and [double]$frequency -gt 0) { $sample['cpu_clock_mhz'] = [double]$frequency }
        } elseif ($item.Name -notmatch '_Total$' -and $null -ne $load) {
            if ($null -eq $coreMax -or $load -gt $coreMax) { $coreMax = $load }
        }
    }
    $sample['cpu_core_max_load_pct'] = $coreMax

    $os = (Get-PCDoctorCim -ClassName 'Win32_OperatingSystem') | Select-Object -First 1
    if ($os -and $os.TotalVisibleMemorySize -gt 0) {
        $sample['ram_used_pct'] = 100.0 * (1.0 - ([double]$os.FreePhysicalMemory / [double]$os.TotalVisibleMemorySize))
    }

    $gotGpu = $false
    $byAdapter = @{}
    if ($NvidiaSmi) {
        try {
            $line = (& $NvidiaSmi '--query-gpu=temperature.gpu,utilization.gpu,power.draw,memory.used,memory.total' '--format=csv,noheader,nounits' 2>$null | Select-Object -First 1)
            if ($line) {
                $parts = @(([string]$line).Split(',') | ForEach-Object { ConvertTo-PCDoctorNumber $_ })
                if ($parts.Count -ge 5) {
                    $sample['gpu_temp_c'] = $parts[0]
                    $sample['gpu_load_pct'] = $parts[1]
                    $sample['gpu_power_w'] = $parts[2]
                    if ($null -ne $parts[3] -and $null -ne $parts[4] -and $parts[4] -gt 0) {
                        $sample['gpu_vram_used_pct'] = [math]::Min(100.0, 100.0 * $parts[3] / $parts[4])
                    }
                    $gotGpu = ($null -ne $parts[1])
                }
            }
        } catch { }
    }
    if (-not $gotGpu) {
        # Task Manager's GPU figure: the busiest adapter's 3D engines, summed
        # over every process using them.
        $engines = Get-PCDoctorCim -ClassName 'Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine' -Filter "Name LIKE '%engtype_3D%'"
        if ($engines.Count -gt 0) {
            foreach ($engine in $engines) {
                $adapter = 'gpu'
                if ($engine.Name -match 'luid_(0x[0-9A-Fa-f]+_0x[0-9A-Fa-f]+)') { $adapter = $Matches[1] }
                if (-not $byAdapter.ContainsKey($adapter)) { $byAdapter[$adapter] = 0.0 }
                $byAdapter[$adapter] += [double]$engine.UtilizationPercentage
            }
            $busiest = ($byAdapter.Values | Measure-Object -Maximum).Maximum
            $sample['gpu_load_pct'] = [math]::Min(100.0, [double]$busiest)
        }
    }
    if ($null -eq $sample['gpu_temp_c'] -and -not $gotGpu) {
        # No NVIDIA card, or nvidia-smi gave nothing: Windows' own adapter
        # counters (Task Manager's GPU temperature), which AMD and Intel
        # drivers fill. Skipped when nvidia-smi gave a load but no
        # temperature: the load is then from a card no LUID is known for.
        $reading = Select-PCDoctorGpuPerfReading -Readings (Get-PCDoctorGpuPerf) -BusiestKey (Select-PCDoctorBusiestGpuKey $byAdapter)
        if ($reading) {
            $sample['gpu_temp_c'] = $reading.temperature_c
            if ($null -eq $sample['gpu_fan_rpm']) { $sample['gpu_fan_rpm'] = $reading.fan_rpm }
        }
    }
    return $sample
}

function Test-PCDoctorUnderLoad {
    # Is a game or stress test running? Asked before a capture starts, so an
    # idle PC is noticed in the first seconds and not after five minutes.
    # A game loads the GPU; a CPU stress test loads only the CPU, so either
    # counts. The limits sit well above the analyzer's "idle" line (median GPU
    # load under 15%) so a run that passes here is not called idle later.
    # Busy is $null when the PC gave no load reading at all: then nothing is
    # known and the capture should simply go ahead.
    param([object[]]$Samples, [double]$GpuLoadPct = 30.0, [double]$CpuLoadPct = 50.0)
    $medians = @{}
    foreach ($column in @('gpu_load_pct', 'cpu_load_pct')) {
        $values = @(foreach ($sample in @($Samples)) {
                if ($sample -and $null -ne $sample[$column]) { [double]$sample[$column] }
            }) | Sort-Object
        $values = @($values)
        if ($values.Count -eq 0) { $medians[$column] = $null; continue }
        $middle = [int][math]::Floor($values.Count / 2)
        if ($values.Count % 2) { $medians[$column] = $values[$middle] }
        else { $medians[$column] = ($values[$middle - 1] + $values[$middle]) / 2.0 }
    }
    $busy = $null
    if ($null -ne $medians['gpu_load_pct'] -or $null -ne $medians['cpu_load_pct']) {
        $busy = (($null -ne $medians['gpu_load_pct'] -and $medians['gpu_load_pct'] -ge $GpuLoadPct) -or
            ($null -ne $medians['cpu_load_pct'] -and $medians['cpu_load_pct'] -ge $CpuLoadPct))
    }
    return [ordered]@{ busy = $busy; gpu_load_pct = $medians['gpu_load_pct']; cpu_load_pct = $medians['cpu_load_pct'] }
}

function Format-PCDoctorLoad {
    # "GPU 3%, CPU 7%" for the messages about an idle PC.
    param($Verdict)
    $parts = @()
    if ($null -ne $Verdict.gpu_load_pct) { $parts += ('GPU {0:0}%' -f $Verdict.gpu_load_pct) }
    if ($null -ne $Verdict.cpu_load_pct) { $parts += ('CPU {0:0}%' -f $Verdict.cpu_load_pct) }
    return ($parts -join ', ')
}

function Format-PCDoctorSensorRow {
    # One CSV line: elapsed seconds, then the columns in their fixed order.
    # Always a dot for decimals, whatever the Windows region settings are.
    param([double]$ElapsedSeconds, [hashtable]$Sample)
    $cells = New-Object System.Collections.Generic.List[string]
    $cells.Add($ElapsedSeconds.ToString('0.00', $script:Invariant))
    foreach ($column in $script:SensorColumns) {
        $value = $Sample[$column]
        if ($null -eq $value) { $cells.Add('') }
        else { $cells.Add(([double]$value).ToString('0.##', $script:Invariant)) }
    }
    return ($cells -join ',')
}

function Get-PCDoctorSensorHeader { 'elapsed_s,' + ($script:SensorColumns -join ',') }

# ------------------------------------------------- CPU temperature driver
# Windows offers no CPU temperature to a plain program. With the owner's
# agreement (docs/plan.md, 2026-11-17) the collector may, during a capture and
# only after asking, install PawnIO - a hardware-access driver signed by
# Microsoft's hardware program - read temperatures with LibreHardwareMonitorLib,
# and remove the driver again when the capture ends. This is the one thing the
# collector ever installs. Every file is checked against temperature-tools.json.

$script:PawnIOUninstallKey = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO'
$script:PawnIOMarker = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'PCDoctor\pawnio-installed-by-pcdoctor.txt'

function Test-PCDoctorFileHash {
    param([string]$Path, [string]$Sha256)
    if (-not $Path -or -not $Sha256 -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    try { return ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -eq $Sha256.ToUpperInvariant()) } catch { return $false }
}

function Get-PCDoctorTemperatureTools {
    # The pinned PawnIO installer and LibreHardwareMonitorLib files next to the
    # collector. $null when any of them is missing or not the pinned file -
    # then none of them is used. Problem is set when the files are there but
    # the installer's signature is wrong.
    param(
        [string]$CollectorDir,
        [scriptblock]$IsTrusted = { param($file, $publisher) Test-PCDoctorSignedBy -Path $file -Publisher $publisher }
    )
    $pinFile = Join-Path $CollectorDir 'temperature-tools.json'
    if (-not (Test-Path -LiteralPath $pinFile)) { return $null }
    try { $pins = Get-Content -LiteralPath $pinFile -Raw | ConvertFrom-Json } catch { return $null }
    if (-not $pins.pawnio -or -not $pins.libraries) { return $null }
    $tools = Join-Path $CollectorDir 'tools'
    $installer = Join-Path $tools ([string]$pins.pawnio.file)
    if (-not (Test-PCDoctorFileHash -Path $installer -Sha256 ([string]$pins.pawnio.sha256))) { return $null }
    $libDir = Join-Path $tools 'lhm'
    foreach ($library in @($pins.libraries)) {
        $name = (([string]$library.dll) -split '/')[-1]
        if (-not (Test-PCDoctorFileHash -Path (Join-Path $libDir $name) -Sha256 ([string]$library.dll_sha256))) { return $null }
    }
    $result = [ordered]@{ Installer = $installer; LibraryDir = $libDir; Version = [string]$pins.pawnio.version; Problem = $null }
    if (-not (& $IsTrusted $installer ([string]$pins.pawnio.signer))) {
        $result.Problem = "The PawnIO installer does not carry a valid signature from $($pins.pawnio.signer), so it was not used and there is no CPU temperature in this run."
    }
    return $result
}

function Test-PCDoctorPawnIOInstalled { Test-Path -LiteralPath $script:PawnIOUninstallKey }

function Get-PCDoctorPawnIOInf {
    # The published name (oemNN.inf) of PawnIO's driver package, for removal.
    $driver = @(Get-PCDoctorCim -ClassName 'Win32_PnPSignedDriver' -Filter "DeviceName = 'PawnIO'") | Select-Object -First 1
    if ($driver -and ([string]$driver.InfName) -match '^oem\d+\.inf$') { return [string]$driver.InfName }
    return $null
}

function Get-PCDoctorPawnIOLeftovers {
    # What of PawnIO is still on this PC. Locale-independent checks only:
    # registry, folders, the service and the device.
    $left = [ordered]@{
        registered    = (Test-PCDoctorPawnIOInstalled)
        folder        = (Test-Path -LiteralPath (Join-Path $env:ProgramFiles 'PawnIO'))
        service       = [bool](Get-Service -Name 'PawnIO' -ErrorAction SilentlyContinue)
        driver_store  = [bool](Get-ChildItem -LiteralPath (Join-Path $env:SystemRoot 'System32\DriverStore\FileRepository') -Directory -Filter 'pawnio.inf_*' -ErrorAction SilentlyContinue)
        device        = $false
    }
    try { $left.device = [bool](Get-PnpDevice -InstanceId 'ROOT\PAWNIO\0000' -ErrorAction Stop) } catch { }
    $left.clean = -not ($left.registered -or $left.folder -or $left.service -or $left.driver_store -or $left.device)
    return $left
}

function Install-PCDoctorPawnIO {
    # Installs PawnIO silently and notes that PC Doctor did it, so a later run
    # can remove it if this one is cut short. Returns the driver package name
    # (needed for removal) or $null when the install failed.
    param([string]$Installer)
    try {
        $process = Start-Process -FilePath $Installer -ArgumentList '-install', '-silent' -Wait -PassThru -WindowStyle Hidden -ErrorAction Stop
    } catch { return $null }
    if (-not (Test-PCDoctorPawnIOInstalled)) { return $null }
    $inf = Get-PCDoctorPawnIOInf
    try {
        New-Item -ItemType Directory -Path (Split-Path -Parent $script:PawnIOMarker) -Force | Out-Null
        [System.IO.File]::WriteAllText($script:PawnIOMarker, ("installed {0} by the PC Doctor collector; package {1}; exit code {2}" -f (Get-Date).ToString('s'), $inf, $process.ExitCode))
    } catch { }
    if ($inf) { return $inf }
    return 'unknown'
}

function Uninstall-PCDoctorPawnIO {
    # PawnIO's own uninstaller, then what it was seen to leave behind on
    # Windows Server 2025 (2026-11-24): the device, the driver package in the
    # driver store and a stopped service. Returns what is left.
    param([string]$Installer, [string]$Inf)
    if (-not $Inf -or $Inf -eq 'unknown') { $Inf = Get-PCDoctorPawnIOInf }
    if ($Installer -and (Test-Path -LiteralPath $Installer)) {
        try { Start-Process -FilePath $Installer -ArgumentList '-uninstall', '-silent' -Wait -WindowStyle Hidden -ErrorAction Stop } catch { }
    } elseif (Test-PCDoctorPawnIOInstalled) {
        $folder = [string](Get-ItemProperty -LiteralPath $script:PawnIOUninstallKey -Name InstallLocation -ErrorAction SilentlyContinue).InstallLocation
        $uninstaller = $(if ($folder) { Join-Path $folder 'uninstall.exe' })
        if ($uninstaller -and (Test-Path -LiteralPath $uninstaller) -and (Test-PCDoctorSignedBy -Path $uninstaller -Publisher 'namazso')) {
            try { Start-Process -FilePath $uninstaller -ArgumentList '-uninstall', '-silent' -Wait -WindowStyle Hidden -ErrorAction Stop } catch { }
        }
    }
    Start-Sleep -Seconds 2
    $pnputil = Join-Path $env:SystemRoot 'System32\pnputil.exe'
    try { if (Get-PnpDevice -InstanceId 'ROOT\PAWNIO\0000' -ErrorAction Stop) { & $pnputil /remove-device 'ROOT\PAWNIO\0000' | Out-Null } } catch { }
    if ($Inf -match '^oem\d+\.inf$') { & $pnputil /delete-driver $Inf /uninstall /force | Out-Null }
    if (Get-Service -Name 'PawnIO' -ErrorAction SilentlyContinue) {
        & (Join-Path $env:SystemRoot 'System32\sc.exe') stop PawnIO | Out-Null
        & (Join-Path $env:SystemRoot 'System32\sc.exe') delete PawnIO | Out-Null
    }
    Start-Sleep -Seconds 1
    $left = Get-PCDoctorPawnIOLeftovers
    if ($left.clean) { Remove-Item -LiteralPath $script:PawnIOMarker -Force -ErrorAction SilentlyContinue }
    return $left
}

function Test-PCDoctorPawnIOLeftBehind {
    # A capture cut short (the window closed) leaves the driver PC Doctor
    # installed. True when the marker says so and PawnIO is still there.
    return ((Test-Path -LiteralPath $script:PawnIOMarker) -and -not (Get-PCDoctorPawnIOLeftovers).clean)
}

# LibreHardwareMonitorLib runs in its own Windows PowerShell 5.1 process: its
# libraries are built for .NET Framework, and the driver handle it holds is
# closed for certain when that process ends, before the driver is removed. It
# writes every sensor, once a second, in the shape of LibreHardwareMonitor's
# web server, so ConvertTo-PCDoctorSample reads it unchanged.
$script:LhmReaderScript = @'
param([string]$LibDir, [string]$OutFile, [string]$StopFile, [int]$ParentId)
$ErrorActionPreference = 'Stop'
trap {
    # Why the reader stopped, for the collector's log.
    $text = $_.Exception.GetType().FullName + ': ' + $_.Exception.Message
    $inner = $_.Exception.InnerException
    while ($inner) { $text += ' <- ' + $inner.GetType().FullName + ': ' + $inner.Message; $inner = $inner.InnerException }
    if ($_.Exception -is [System.Reflection.ReflectionTypeLoadException]) {
        $text += ' | ' + (($_.Exception.LoaderExceptions | ForEach-Object { $_.Message } | Select-Object -Unique -First 3) -join ' | ')
    }
    if ($_.InvocationInfo) { $text += ' (line ' + $_.InvocationInfo.ScriptLineNumber + ': ' + $_.InvocationInfo.Line.Trim() + ')' }
    [System.IO.File]::WriteAllText($OutFile + '.error', $text)
    exit 1
}
Add-Type -TypeDefinition @"
using System; using System.IO; using System.Reflection;
public static class PCDoctorLhmResolver {
    public static string Dir;
    public static void Enable() {
        AppDomain.CurrentDomain.AssemblyResolve += delegate(object sender, ResolveEventArgs e) {
            string file = Path.Combine(Dir, new AssemblyName(e.Name).Name + ".dll");
            return File.Exists(file) ? Assembly.LoadFrom(file) : null;
        };
    }
}
"@
[PCDoctorLhmResolver]::Dir = $LibDir
[PCDoctorLhmResolver]::Enable()
Add-Type -Path (Join-Path $LibDir 'LibreHardwareMonitorLib.dll')
$computer = New-Object LibreHardwareMonitor.Hardware.Computer
$computer.IsCpuEnabled = $true
$computer.Open()
# The CPU first, then each other group on its own: one that fails on this
# hardware (seen on GitHub's VM, 2026-11-24) must not cost the CPU reading.
$skipped = @()
foreach ($group in @('IsGpuEnabled', 'IsMemoryEnabled')) {
    try { $computer.$group = $true } catch { $skipped += $group + ': ' + $_.Exception.Message }
}
if ($skipped) { [System.IO.File]::WriteAllText($OutFile + '.skipped', ($skipped -join ' | ')) }
$deadline = (Get-Date).AddHours(3)
try {
    while (-not (Test-Path -LiteralPath $StopFile) -and (Get-Date) -lt $deadline) {
        if ($ParentId -and -not (Get-Process -Id $ParentId -ErrorAction SilentlyContinue)) { break }
        $sensors = New-Object System.Collections.Generic.List[object]
        $stack = New-Object System.Collections.Generic.Stack[object]
        foreach ($hardware in $computer.Hardware) { $stack.Push($hardware) }
        while ($stack.Count -gt 0) {
            $hardware = $stack.Pop()
            try { $hardware.Update() } catch { continue }
            foreach ($sub in $hardware.SubHardware) { $stack.Push($sub) }
            foreach ($sensor in $hardware.Sensors) {
                try {
                    $value = $null
                    if ($null -ne $sensor.Value) { $value = [math]::Round([double]$sensor.Value, 2) }
                    $sensors.Add([pscustomobject]@{ SensorId = $sensor.Identifier.ToString(); Type = [string]$sensor.SensorType; Text = [string]$sensor.Name; Value = $value })
                } catch { }
            }
        }
        $temp = $OutFile + '.tmp'
        # ToArray, not @(): Windows PowerShell 5.1 throws "Argument types do not
        # match" for @() around a generic list here (GitHub's runner, 2026-11-24).
        [System.IO.File]::WriteAllText($temp, (ConvertTo-Json -InputObject $sensors.ToArray() -Depth 3 -Compress))
        Move-Item -LiteralPath $temp -Destination $OutFile -Force
        Start-Sleep -Milliseconds 900
    }
} finally { $computer.Close() }
'@

function Start-PCDoctorLhmReader {
    # Starts the reader process; returns where it writes, or $null.
    param([string]$LibraryDir)
    $work = Join-Path ([System.IO.Path]::GetTempPath()) ('pcdoctor-lhm-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    try {
        New-Item -ItemType Directory -Path $work -Force | Out-Null
        $scriptPath = Join-Path $work 'reader.ps1'
        [System.IO.File]::WriteAllText($scriptPath, $script:LhmReaderScript, (New-Object System.Text.UTF8Encoding($false)))
        $reader = [ordered]@{ Dir = $work; OutFile = (Join-Path $work 'sensors.json'); StopFile = (Join-Path $work 'stop'); Process = $null }
        $windowsPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"{0}"' -f $scriptPath),
            '-LibDir', ('"{0}"' -f $LibraryDir), '-OutFile', ('"{0}"' -f $reader.OutFile), '-StopFile', ('"{0}"' -f $reader.StopFile), '-ParentId', [string]$PID)
        $reader.Process = Start-Process -FilePath $windowsPowerShell -ArgumentList $arguments -PassThru -WindowStyle Hidden -ErrorAction Stop
        return $reader
    } catch {
        Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
        return $null
    }
}

function Get-PCDoctorLhmReaderSensors {
    # The reader's latest sensors, or $null when it has written nothing fresh.
    param($Reader, [double]$MaxAgeSeconds = 10)
    if (-not $Reader -or -not (Test-Path -LiteralPath $Reader.OutFile)) { return $null }
    try {
        $age = ((Get-Date) - (Get-Item -LiteralPath $Reader.OutFile).LastWriteTime).TotalSeconds
        if ($age -gt $MaxAgeSeconds) { return $null }
        # Into a variable first: Windows PowerShell 5.1 passes a JSON array on
        # as one object, and @() around the pipeline would nest it.
        $parsed = [System.IO.File]::ReadAllText($Reader.OutFile) | ConvertFrom-Json
        return @($parsed)
    } catch { return $null }
}

function Get-PCDoctorLhmReaderProblem {
    # Why the reader gave nothing: the error it wrote, or that it ended.
    param($Reader)
    if (-not $Reader) { return 'it could not be started' }
    $errorFile = $Reader.OutFile + '.error'
    if (Test-Path -LiteralPath $errorFile) {
        try { return (Protect-PCDoctorText -Text ([System.IO.File]::ReadAllText($errorFile)) -MaxLength 400) } catch { }
    }
    if ($Reader.Process -and $Reader.Process.HasExited) { return "it ended with exit code $($Reader.Process.ExitCode)" }
    return 'it wrote nothing in time'
}

function Stop-PCDoctorLhmReader {
    param($Reader)
    if (-not $Reader) { return }
    try { [System.IO.File]::WriteAllText($Reader.StopFile, 'stop') } catch { }
    if ($Reader.Process) {
        try { if (-not $Reader.Process.WaitForExit(10000)) { $Reader.Process.Kill(); $null = $Reader.Process.WaitForExit(5000) } } catch { }
    }
    Remove-Item -LiteralPath $Reader.Dir -Recurse -Force -ErrorAction SilentlyContinue
}

# ------------------------------------------------------------- PresentMon

function Test-PCDoctorSignedBy {
    # True when the file carries a valid Authenticode signature (embedded or
    # through a Windows catalog) whose certificate names the publisher as its
    # CN or O. Used before running any program as administrator.
    param([string]$Path, [string]$Publisher)
    try {
        $signature = Get-AuthenticodeSignature -LiteralPath $Path -ErrorAction Stop
    } catch {
        return $false
    }
    if ($signature.Status -ne 'Valid' -or -not $signature.SignerCertificate) { return $false }
    $name = [regex]::Escape($Publisher)
    return [bool]($signature.SignerCertificate.Subject -match "(^|,\s*)(CN|O)=`"?$name`"?(,|$)")
}

function Find-PCDoctorPresentMon {
    # Where is PresentMon? An explicit path, then the collector's own tools
    # folder (Get-Tools.ps1 puts it there), then the PATH - but the PATH only
    # when not elevated, because a folder on the PATH may be writable by
    # anyone. Never downloads. Whatever is found must be signed by Intel,
    # checked again here: Get-Tools.ps1 checked the download, but the tools
    # folder could have been changed since (it travels on a USB stick).
    # Returns @{ Path = <path or $null>; Problem = <text or $null> }.
    param(
        [string]$ExplicitPath,
        [string]$ToolsDir,
        [switch]$Elevated,
        [scriptblock]$IsTrusted = { param($file) Test-PCDoctorSignedBy -Path $file -Publisher 'Intel Corporation' }
    )
    $candidates = @()
    if ($ExplicitPath) {
        if (Test-Path -LiteralPath $ExplicitPath -PathType Leaf) { $candidates += (Resolve-Path -LiteralPath $ExplicitPath).Path }
    } else {
        if ($ToolsDir -and (Test-Path -LiteralPath $ToolsDir)) {
            $candidates += @(Get-ChildItem -LiteralPath $ToolsDir -Filter 'PresentMon*.exe' -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending | ForEach-Object { $_.FullName })
        }
        if (-not $Elevated) {
            foreach ($name in @('PresentMon.exe', 'PresentMon-x64.exe')) {
                $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($command) { $candidates += $command.Source }
            }
        }
    }
    if ($candidates.Count -eq 0) { return @{ Path = $null; Problem = $null } }
    foreach ($candidate in $candidates) {
        if (& $IsTrusted $candidate) { return @{ Path = $candidate; Problem = $null } }
    }
    return @{
        Path    = $null
        Problem = 'A PresentMon program was found but it does not carry a valid Intel signature, so it was not run. Delete the tools folder and run Get-Tools.ps1 again.'
    }
}

function Get-PCDoctorPresentMonArguments {
    # Flags were run for real against PresentMon 2.6.0 (docs/verified-facts.md).
    param([string]$OutputFile, [int]$Seconds, [string]$Process)
    $arguments = @(
        '--output_file', ('"{0}"' -f $OutputFile),
        '--timed', [string]$Seconds,
        '--terminate_after_timed',
        '--no_console_stats',
        '--stop_existing_session',
        '--session_name', 'PCDoctor'
    )
    if ($Process) { $arguments += @('--process_name', ('"{0}"' -f $Process)) }
    return , $arguments
}

function Select-PCDoctorPresentMonRows {
    # PresentMon records every program that draws to the screen. Keep only the
    # one being tested - the named process, or the busiest one that is not part
    # of the Windows shell - so the names of other running programs never leave
    # the PC. Returns what was kept.
    param([string]$Path, [string]$Destination, [string]$Process)
    $result = [ordered]@{ application = $null; frames = 0; other_processes_removed = 0 }
    if (-not (Test-Path -LiteralPath $Path)) { return $result }

    $counts = @{}
    $reader = New-Object System.IO.StreamReader($Path)
    try {
        $header = $reader.ReadLine()
        if ($null -eq $header) { return $result }
        $columns = @($header.Split(','))
        $appIndex = -1
        for ($i = 0; $i -lt $columns.Count; $i++) {
            if ($columns[$i].Trim().Trim([char]0xFEFF) -ieq 'Application') { $appIndex = $i; break }
        }
        if ($appIndex -lt 0) {
            # Not a layout we know: keep the file as it is rather than lose data.
            $reader.Close()
            Copy-Item -LiteralPath $Path -Destination $Destination -Force
            return $result
        }
        while ($null -ne ($line = $reader.ReadLine())) {
            if ($line.Length -eq 0) { continue }
            $app = ($line.Split(',', $appIndex + 2)[$appIndex]).Trim()
            if ($counts.ContainsKey($app)) { $counts[$app]++ } else { $counts[$app] = 1 }
        }
    } finally { $reader.Close() }
    if ($counts.Count -eq 0) { return $result }

    $chosen = $null
    if ($Process) {
        $wanted = $Process.Trim()
        foreach ($app in $counts.Keys) {
            if ($app -ieq $wanted -or $app -ieq ($wanted + '.exe')) { $chosen = $app; break }
        }
    }
    if (-not $chosen) {
        $pool = @($counts.Keys | Where-Object { $script:ShellProcesses -notcontains $_.ToLowerInvariant() })
        if ($pool.Count -eq 0) { $pool = @($counts.Keys) }
        $chosen = $pool | Sort-Object { $counts[$_] } -Descending | Select-Object -First 1
    }

    $reader = New-Object System.IO.StreamReader($Path)
    $writer = New-Object System.IO.StreamWriter($Destination, $false, (New-Object System.Text.UTF8Encoding($false)))
    try {
        $writer.WriteLine($reader.ReadLine())
        while ($null -ne ($line = $reader.ReadLine())) {
            if ($line.Length -eq 0) { continue }
            $app = ($line.Split(',', $appIndex + 2)[$appIndex]).Trim()
            if ($app -eq $chosen) { $writer.WriteLine($line) }
        }
    } finally {
        $writer.Close()
        $reader.Close()
    }
    $result.application = $chosen
    $result.frames = $counts[$chosen]
    $result.other_processes_removed = $counts.Count - 1
    return $result
}

# ----------------------------------------------------------------- upload

function Send-PCDoctorRun {
    # POST the zip to a PC Doctor server. Returns the server's answer, or
    # throws with a message worth showing.
    param([string]$ZipPath, [string]$Url, [string]$Label)
    Add-Type -AssemblyName System.Net.Http
    $client = New-Object System.Net.Http.HttpClient
    $client.Timeout = [TimeSpan]::FromSeconds(120)
    $stream = [System.IO.File]::OpenRead($ZipPath)
    try {
        $form = New-Object System.Net.Http.MultipartFormDataContent
        $file = New-Object System.Net.Http.StreamContent($stream)
        $file.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse('application/zip')
        $form.Add($file, 'file', [System.IO.Path]::GetFileName($ZipPath))
        if ($Label) { $form.Add((New-Object System.Net.Http.StringContent($Label)), 'label') }
        $response = $client.PostAsync(($Url.TrimEnd('/') + '/api/runs'), $form).GetAwaiter().GetResult()
        $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            throw "The server answered $([int]$response.StatusCode): $body"
        }
        return ($body | ConvertFrom-Json)
    } finally {
        $stream.Dispose()
        $client.Dispose()
    }
}

function Get-PCDoctorResultLink {
    # The address of the diagnosis after an upload, built only from parts that
    # have the expected shape: an http(s) server, a private key of URL-safe
    # characters or a 32-character run id. Anything else from the server gives
    # no link at all, so a hostile answer cannot make the collector open some
    # other address.
    param([string]$BaseUrl, $Answer)
    $base = $BaseUrl.TrimEnd('/')
    if ($base -notmatch '^https?://[^\s/?#]+$') { return $null }
    $key = [string]$Answer.share_key
    if ($key) {
        if ($key -cmatch '^[A-Za-z0-9_-]{16,128}$') { return "$base/r/$key" }
        return $null
    }
    $id = [string]$Answer.run.id
    if ($id -cmatch '^[0-9a-f]{32}$') { return "$base/runs/$id" }
    return $null
}

Export-ModuleMember -Function *-PCDoctor*
