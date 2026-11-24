# pcdoctor-capture (Rust)

The **capture part** of the PC Doctor collector, in Rust: frame times from
PresentMon and sensor readings from LibreHardwareMonitor, written in the same
run format as the PowerShell collector (`docs/run-format.md`), so the analyzer
and the dashboard read it unchanged. It exists to find out whether a native
collector disturbs a running game less than PowerShell does (plan Step 5.1).

It does **not** replace `collector/`: it reads no specs, events or disk health.
When LibreHardwareMonitor is not running it falls back to Windows' own
counters (load, speed, RAM, GPU load - no temperatures), like the PowerShell
collector, but without `nvidia-smi`.

**Read-only.** It changes no settings and installs nothing. It reads
PresentMon's CSV and LibreHardwareMonitor's `data.json`, and writes a folder and
a zip next to itself.

## What it writes

`PCDoctor-run-yyyyMMdd-HHmmss/` (local time) and a `.zip` of the same name,
with the files at the top level of the zip:

| File | Contents |
|---|---|
| `presentmon.csv` | PresentMon's rows for the tested program only, unchanged, header included. Any PresentMon header style (1.x `msBetweenPresents`, 2.x `MsBetweenPresents`, `--v2_metrics` `FrameTime`) |
| `sensors.csv` | `elapsed_s` + the 14 fixed columns, one row per interval. `cpu_perf_pct` is always empty (it comes from Windows counters, which this collector does not read) |
| `sensors_raw.json` | One snapshot of the sensor list (`SensorId`, `Type`, `Text`, `Value`) - sensor nodes only, no hardware or computer names |
| `manifest.json` | The PowerShell collector's fields (`schema_version` 1, `capture.presentmon`, `capture.sensors`, ...), `mode: "capture"`, `collector.name: "pcdoctor-capture-rs"`, `event_window_days` and `is_admin` set to `null` (not read). Extra keys the analyzer ignores: `collector_resources`, `capture.presentmon.other_frames_removed`, `capture.presentmon.columns` |
| `collector.log` | What it did, and warnings. No file paths |

Privacy (docs/privacy.md): rows of other programs are dropped as they arrive
and only *counted* (`other_processes_removed`, `other_frames_removed`); their
names are not even kept in memory (only a hash, to count distinct programs).
PresentMon's unfiltered CSV, when this program started PresentMon, is deleted
at the end and is never put in the zip. The label is scrubbed like the
PowerShell collector's (user folders, serial numbers, computer and user name).
No computer name, user name, serial number or file path is written.

## Build

Needs Rust 1.80 or newer (`rustup`, <https://rustup.rs>).

```sh
cd collector-rs
cargo build --release          # target/release/pcdoctor-capture(.exe)
cargo test                     # unit tests + end-to-end tests on fixtures
cargo fmt --check
cargo clippy --all-targets -- -D warnings
scripts/check-with-analyzer.sh # makes a run zip from fixtures and runs pcdoctor-analyze on it
```

On Windows, `cargo build --release` with the MSVC toolchain (Visual Studio
Build Tools) gives `target\release\pcdoctor-capture.exe`, a single file that
can sit on the USB stick next to `collector\`.

## Run on Windows

As administrator (PresentMon needs it to record frames), with
LibreHardwareMonitor running and Options > Remote Web Server > Run switched on:

```powershell
# Start PresentMon itself and capture 5 minutes. --start-presentmon takes the exact
# path of the PresentMon file. The collector zip has it as
# PCDoctor-collector\tools\PresentMon-2.6.0-x64.exe; in a git checkout run
# collector\Get-Tools.ps1 first to fetch it into collector\tools. The file is not
# checked for a signature, so use the one from the zip or Get-Tools.ps1.
.\pcdoctor-capture.exe --process Game.exe --seconds 300 `
    --start-presentmon ..\collector\tools\PresentMon-2.6.0-x64.exe --label "bench 3"

# Or follow a CSV that a PresentMon you started yourself is writing:
.\pcdoctor-capture.exe --process Game.exe --seconds 300 --presentmon-csv C:\temp\pm.csv

.\pcdoctor-capture.exe --help
```

Other flags: `--lhm-url` (default `http://localhost:8085/data.json`),
`--lhm-file` (a saved `data.json`, for tests), `--no-sensors`, `--interval`
(default 1 s), `--output-dir` (default: `runs` next to the program),
`--start-delay`, `--no-zip`. Drop the zip on the dashboard's Runs page.

At the end it prints its own CPU time and peak memory, and writes them to
`manifest.json` under `collector_resources`.

## Live view (optional)

On the master, open **Live** in the dashboard and start a session. It shows a
samples address once. Give it to the collector:

```
pcdoctor-capture --process Game.exe --start-presentmon tools\PresentMon-2.6.0-x64.exe --live-url https://pcdoctor.example.com/api/live/<token>/samples
```

About once a second the collector sends the new frame times and sensor
readings (NDJSON: `{"type":"frame","t":..,"ms":..}`, `{"type":"sensor",...}`,
and `{"type":"end"}` at the end), and the Live page draws them. Only frame
times and sensor values are sent: no program names, paths or anything else.
`https://` is required, except to this PC or a private network address
(`http://192.168.x.x`, `http://localhost`). Streaming is best effort: if the
server cannot be reached, lines wait and the capture carries on; the run on
disk is the record and is uploaded as usual. The token can only add samples
to that one session.

Tested end to end in the build container: the binary followed a growing
PresentMon file from the fixtures and streamed 900 frames and 10 sensor
readings into a running API; the Live page showed the same average FPS as
the analyzer. Not tested over HTTPS or from a real Windows PC.

## Comparing its overhead with the PowerShell collector

The question is what each collector costs the PC *while a game runs*. To
measure it fairly:

- **Same PC, same game, same scene**, one after the other, at least 3 runs
  each (alternate the order), 300 s each, 1 s sensor interval, LibreHardwareMonitor
  running for both, PresentMon 2.6.0 for both. Note the PC (CPU, GPU, RAM,
  Windows build) with the numbers. A low-end PC (4 cores) shows differences
  best; a fast one shows whether they matter at all.
- **Collector CPU time and peak memory.** Rust: `collector_resources` in the
  manifest (`cpu_seconds`, `peak_memory_bytes` = peak working set). PowerShell:
  run it with `-NonInteractive` and read the `powershell.exe` process's
  `TotalProcessorTime` and `PeakWorkingSet64` at the end, e.g. in a second
  window: `Get-Process powershell | Select TotalProcessorTime, PeakWorkingSet64`
  just before it exits, or use Windows Performance Recorder / Process Explorer.
  Count only the collector process in both cases: PresentMon and
  LibreHardwareMonitor are the same programs either way, so leave them out (or
  measure them separately and check they are the same).
- **What the game feels.** Average FPS and 1% low from the analyzer for each
  run, and the same with no collector at all (PresentMon alone) as the
  baseline. A difference smaller than the run-to-run spread is no difference.
- **Sampling accuracy.** `sensors.samples` against `actual_seconds` (does each
  collector manage one sample per second under load?).

Record the results in `docs/results.md` with the PC they came from. No numbers
are given here because none have been measured yet.

## How it works

`src/lib.rs` holds all the logic so it is tested on Linux; `src/main.rs` only
runs the capture loop. One thread: every 250 ms it reads whatever PresentMon
appended (a partial last line is held back until its newline arrives), and on
a fixed schedule it reads LibreHardwareMonitor. The sensor mapping is a port of
`ConvertTo-PCDoctorSample` in `collector/PCDoctorCollector.psm1`, with the same
sensor names and fallbacks.

Known differences from the PowerShell collector:

- `--process` is required: rows are filtered as they arrive, so the program
  must be known up front (the PowerShell collector can pick the busiest program
  after the capture).
- When LibreHardwareMonitor does not answer, it reads Windows' counters
  (`src/winsensors.rs`: PDH under English counter names, and
  `GlobalMemoryStatusEx`) for CPU load, busiest core, CPU speed, RAM and GPU
  load, and the manifest says `"source": "windows"`. It does not run
  `nvidia-smi` (the PowerShell collector does, after checking NVIDIA's
  signature), so an NVIDIA card's temperature and power are missing then.
  The counter code has only been compiled for Windows, never run there with
  a real PC: CI builds and tests it on windows-latest.
- When several sensors could fill one column (e.g. two GPU fans), it takes the
  first in `data.json` order; the PowerShell collector's tree walk ends up
  taking the last.
- Files end lines with `\n`, not `\r\n` (every reader accepts both).

## Not verified

Never run on Windows with a real game, a real PresentMon or a real
LibreHardwareMonitor. What was checked, on Linux: unit and end-to-end tests
with fixture files (PresentMon 1.x / 2.x / `--v2_metrics` column names from
`docs/verified-facts.md`, `data.json` shaped as LibreHardwareMonitor's
`HttpServer.cs` writes it), the analyzer reading the zip with no "could not be
read" notes, and `cargo check`/`clippy` for `x86_64-pc-windows-gnu` (no link).
Things to check first on a gaming PC:

1. Whether PresentMon lets another program read its CSV while writing it. If
   it opens the file without read sharing, `pcdoctor-capture` cannot open it
   until PresentMon exits, and then reads it all at the end (same result, but
   not live) - check that `frames` in the manifest is non-zero.
2. That `--start-presentmon` passes paths with spaces correctly (Rust quotes
   each argument itself).
3. The sensor mapping on real hardware: compare `sensors_raw.json` with
   `sensors.csv`.
4. The overhead numbers above.
