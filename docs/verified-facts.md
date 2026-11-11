# Verified facts

The plan says: verify every event id and command against the source before
relying on it. This page records what was checked, how, and what was not.

Microsoft's documentation site could not be opened from the build environment,
so Windows facts were taken from **Windows itself**: the
[`windows-facts`](../.github/workflows/windows-facts.yml) workflow runs on a
real Windows machine and prints the event definitions, storage classes and
stop-code names that ship with Windows. Run it again from the Actions tab
whenever you want to re-check (for example after a major Windows release).

Checked on 2026-11-11 against Windows Server 2025, build 10.0.26100, and the
Windows SDK 10.0.26100.

## Windows events

| Fact | Checked against |
|---|---|
| `Microsoft-Windows-Kernel-Power` 41, Critical: "The system has rebooted without cleanly shutting down first." Data fields include `BugcheckCode`, `PowerButtonTimestamp`, `LongPowerButtonPressDetected` | Provider definition |
| `Microsoft-Windows-Kernel-Power` 86, Error: "The system was shut down due to a critical thermal event." | Provider definition |
| `Microsoft-Windows-WER-SystemErrorReporting` 1001: "The computer has rebooted from a bugcheck. The bugcheck was: %1." (`param1` holds the stop code). 1000 and 1006 are the variants without a saved dump; 1019 names a "possibly related driver" (`SuspectedDriver`) | Provider definition |
| `Microsoft-Windows-MemoryDiagnostics-Results`: 1101 and 1201 = no errors; 1102 and 1202 = hardware errors detected; 1103 = cancelled; 1104 = could not complete | Provider definition |
| `Microsoft-Windows-Kernel-Processor-Power` 37, Warning: "The speed of processor %2 in group %1 is being limited by system firmware." | Provider definition |
| `Microsoft-Windows-WHEA-Logger`: fatal ids 1, 16, 18, 20, 22, 24, 26, 29, 40, 42, 44, 46, 48; corrected ids 2, 17, 19, 21, 23, 25, 27, 28, 41, 43, 45, 47, 49; 3 is informational. 18/19/28/29 = Processor Core, 20/21 = AMD Northbridge, 22/23/46-49 = Memory, 24/25/42/43 = PCI/PCI-X Bus, 26/27/44/45 = PCI/PCI-X Device | Provider definition |
| `Ntfs` 55, Error: "A corruption was discovered in the file system structure on volume %1." | Provider definition |
| Event 29 of WHEA-Logger says "fatal" but is logged at Warning level - which is why the rules go by id, not level | Provider definition |

**Not machine-checked:** `disk` 7 / 11 / 51 / 52 / 153, `storahci` 129,
`stornvme` 11 / 129 and `Display` 4101. Those providers are older "classic"
ones with no readable definition on the test machine. The ids used are the
long-documented ones; confirm them against a machine that has such events
(Event Viewer > System) when one comes through the shop.

## Storage

- `Get-StorageReliabilityCounter` properties used: `Temperature`,
  `TemperatureMax`, `Wear`, `ReadErrorsTotal`, `ReadErrorsUncorrected`,
  `WriteErrorsTotal`, `WriteErrorsUncorrected`, `PowerOnHours`,
  `StartStopCycleCount` - all present on `MSFT_StorageReliabilityCounter`.
- `Get-PhysicalDisk` returns `HealthStatus`, `MediaType` and `BusType` as words
  ("Healthy", "SSD", "NVMe"), and that is how they are stored.
- A virtual disk reports temperature 0 and empty error counters: the rules
  treat 0 °C as "not reported".
- **Not confirmed:** that `Wear` means "percent of rated life used". It is
  documented that way and read that way; check it against a drive maker's tool
  on a worn SSD.

## Stop codes

All stop-code names in `workers/pcdoctor_analysis/stopcodes.py` were compared
with `bugcodes.h` from the Windows SDK (545 codes). The plain-English
meanings, causes and checks are technician guidance written for this project,
not Microsoft text.

## PresentMon

Checked by downloading and running PresentMon 2.6.0 (the latest release,
2026-09-21) on Windows, and by reading its source (`CsvOutput.cpp`):

- The flags the collector uses are accepted: `--output_file`, `--timed`,
  `--terminate_after_timed`, `--no_console_stats`, `--stop_existing_session`,
  `--session_name`, `--process_name`.
- The standalone program is `PresentMon-2.6.0-x64.exe`, signed by Intel
  Corporation, SHA-256 `B2A706BC6AD475749E3B7E3409263AA1E6906D45BDCF993F6DBC0F660188F1AF`.
  `Get-Tools.ps1` checks both before keeping the file.
- It prints its banner on **stderr**. In Windows PowerShell, merging that with
  `2>&1` turns it into an error, so the collector starts it with
  `Start-Process` and sends its output to files.
- When nothing draws to the screen it exits 0 and writes **no CSV**. The
  collector reports that as a warning instead of failing.
- CSV column names by mode (the parser accepts all of them):

  | Mode | Frame time | Timestamp | GPU busy |
  |---|---|---|---|
  | default | `MsBetweenPresents` | `TimeInSeconds` | `MsGPUBusy` |
  | `--v2_metrics` | `FrameTime` | `CPUStartTime` | `GPUBusy` |
  | `--v1_metrics` | `msBetweenPresents` | `TimeInSeconds` | `msGPUActive` |

**Not verified:** a capture of a real game. The test machine has no display,
so PresentMon ran correctly but recorded no frames. First thing to check on a
gaming PC.

## LibreHardwareMonitor

Read from its source (latest release 0.9.6):

- The current app has **no WMI provider** (older guides mention one). The way
  to read it from another program is its built-in web server: Options > Remote
  Web Server > Run, port 8085, `http://localhost:8085/data.json`. It is off by
  default.
- Sensor nodes carry `SensorId` (for example `/intelcpu/0/temperature/8`),
  `Type`, `Text`, `Value` (formatted, e.g. "45.0 °C") and `RawValue` (a plain
  number). The collector uses `RawValue` and falls back to parsing `Value`.
- Sensor names used for the mapping come from `IntelCpu.cs`, `Amd17Cpu.cs`,
  `GenericCpu.cs`, `NvidiaGpu.cs`, `AmdGpu.cs` and `TotalMemory.cs`.

**Not verified:** readings from a real LibreHardwareMonitor on real hardware.
The mapping is unit-tested against the names in the source, and the collector
saves one raw snapshot (`sensors_raw.json`) per capture so a wrong mapping on
unusual hardware can be seen and fixed.

## Windows sensors without extra tools

On the test machine the CIM classes the collector falls back to returned live
values: CPU load, busiest core, clock speed (MHz), speed relative to rated
speed, GPU load and RAM use. These classes are used instead of `Get-Counter`
because performance counter names are translated on a non-English Windows.
Windows offers no reliable CPU temperature, which is why LibreHardwareMonitor
is recommended.
