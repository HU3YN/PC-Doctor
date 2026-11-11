# Privacy: what the collector reads, what it never reads, what it uploads

PC Doctor is about hardware and performance. It has no interest in who uses a
PC or what they do on it. This page is the full list. The collector is open
source and short, so you can check every line of it:
[`collector/PCDoctorCollector.psm1`](../collector/PCDoctorCollector.psm1).

## The collector is read-only

It changes no settings, installs no drivers and no software, and runs no
fixes. It reads, and writes its findings to one folder.

## What it reads

| What | Where from | Why |
|---|---|---|
| CPU, graphics card, motherboard and BIOS model and version | Windows (CIM) | To describe the build and compare it with others |
| Memory modules: size, speed, part number, slot | Windows (CIM) | Single-channel RAM, XMP off, mixed kits |
| Graphics driver version and date; screen resolution and refresh rate | Windows (CIM) | Old or missing drivers |
| Windows edition, version, build, last boot time | Windows (CIM) | Context for crashes |
| Active power plan | `powercfg /getactivescheme` | Power saver slows a PC down |
| Battery design and current capacity (laptops) | Windows (WMI) | Worn batteries |
| Disk model, type, firmware, health, wear, temperature, error counts | `Get-PhysicalDisk`, `Get-StorageReliabilityCounter` | Failing or worn drives |
| Size and free space of each drive letter | `Get-Volume` | Full drives |
| Hardware events from the last 30 days: hardware errors (WHEA), unexpected shutdowns, blue-screen stop codes, thermal shutdowns, memory test results, disk errors, graphics driver resets, firmware speed limits | Windows System event log | Crashes and failing parts |
| Frame times of **one** program during a capture | PresentMon | Stutter and frame rate |
| Temperatures, loads, clock speeds, power, fan speed, memory use during a capture | LibreHardwareMonitor, or Windows itself and `nvidia-smi` | Overheating, throttling, bottlenecks |

The exact list of event providers and ids is in `$script:EventQueries`, and the
only event data fields kept are in `$script:EventDataKept`, both at the top of
the module.

## What it never reads

- **No names.** Not the computer name, not user names, not the Windows owner.
- **No serial numbers.** Not of the PC, the board, the disks or the memory.
- **No network identity.** No IP or MAC addresses, no Wi-Fi names.
- **No files.** No file names, folders, documents, or browser data.
- **No list of what is running or installed.** PresentMon sees every program
  that draws to the screen; the collector keeps the rows of the one program
  being tested and deletes the rest before the run is saved. Only a count of
  how many others were removed is kept.
- **No volume labels** (people name drives after themselves).

As a second line of defence, any text taken from Windows (event messages) is
scrubbed before it is saved: user-folder paths, serial numbers, the computer
name and the current user name are replaced with placeholders.

This is tested, not just promised: on every change, CI runs the collector on a
real Windows machine and fails if the computer name, the user name or a serial
number appears anywhere in the output (`collector/tests/Invoke-IntegrationTest.ps1`).

## What is uploaded

Nothing, unless you upload it. The collector writes a folder and a zip next to
itself. You upload the zip by dropping it on the dashboard, or by giving the
collector `-UploadUrl`. The server keeps only the known files from the zip
(`manifest.json`, `specs.json`, `events.json`, `disks.json`, `presentmon.csv`,
`sensors.csv`, `sensors_raw.json`, `collector.log`) and ignores anything else.

Open any of them in Notepad - they are plain text. The format is described in
[run-format.md](run-format.md).

## The work log

The work log is your own notes about repairs. The rule is the same: the
machine and the fix, never the customer. The form says so, and an entry that
looks like it contains an email address, a phone number, a serial number or a
customer's name is flagged with a warning. Your own job number is fine.

## For shop machines (KT Electronics)

- Ask the owner before running the collector on a shop or customer machine.
- Never put customer names, serial numbers or customer data in this
  repository, in sample data, or in the work log.
- The label you type for a run is yours to choose: "bench 3, GPU swap", never
  a customer's name.
