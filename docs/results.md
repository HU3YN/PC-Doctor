# Measured results

Numbers for the resume go here - and only numbers that were measured, with
their context (which test set, how many cases, which machine). Nothing in this
file is an estimate. An empty row is honest; a guessed number is not.

When something here is measured, add it to the Application Helper project's
master reference too.

## What is verified today (2026-11-14)

These are test results, not accuracy claims. All of them ran in the cloud
build container or in GitHub Actions; none ran on the owner's PC.

| Check | Result |
|---|---|
| Analysis package unit tests | 148 pass (Python 3.11 and 3.13), including 25 regression tests for crashes the fuzzers found |
| API tests | 245 pass on SQLite and on PostgreSQL 16 (2026-11-15), including access control: every API route is checked to be master-only, signed-in-only or deliberately public |
| Dashboard unit tests | 6 pass; lint and type check clean |
| Sign-in pages, member view, Account page, Live page, build comparison | Driven in a real browser (Playwright, desktop and phone sizes) with stand-in Discord/Google ids: no console errors, no sideways scrolling |
| Go upload service | 10 tests pass with the race detector; fuzzed in CI |
| Discord bot | 130 tests pass against a stand-in API. **Never run on a real Discord server** |
| Rust capture collector | 60 tests pass on Linux (61 on Windows, including a real signature check); builds and tests on windows-latest in CI; the analyzer reads its output with no notes. **Never run with a real game** |
| Live view | The Rust collector streamed a fixture capture (900 frames, 10 sensor readings) into a running API in the build container; the Live page showed the same average FPS (138.4) as the analyzer. Not tested over HTTPS |
| Sensor node | 24 host C tests and 35 receiver tests pass. **The firmware has never been compiled for the ESP32 or run on hardware** |
| Frame-time model, LED reader | 29 and 23 tests pass on CPU. Trained only on synthetic data (see below) |
| Evaluation scripts | 21 tests pass |
| AI helper and troubleshooter | Tested against a stand-in for the AI service only. **Never run against the real API** |
| Photo reading | Reads the stop code from generated blue-screen images, including with a dark border and a 2 degree tilt (regression tests). **Not measured on real phone photos** |
| Collector on real Windows (GitHub runner) | Lint clean; unit tests pass on Windows PowerShell 5.1 and PowerShell 7; quick run and capture run complete; output contains no computer name, user name or serial number; the analyzer reads it |
| Fault types the rules engine can detect | 29 (`pcdoctor-analyze rules`) |
| Synthetic sample runs | 8 of 8 get their expected diagnosis - a plumbing check only; the rules were written against these |

**Not verified yet:** frame-time capture on a PC with a real game and a real
display, LibreHardwareMonitor readings on real hardware, diagnosis accuracy on
real faults, photo reading on real photos, the AI features against the real
API, real Discord/Google sign-in, the bot on a real server, Terraform and k3s
on a real AWS account, k6 numbers on a real machine, the sensor node on
hardware. [testing.md](testing.md) lists what only the owner's PC, phone or
accounts can prove.

## First run on real hardware (2026-11-15)

The owner's own PC: AMD Ryzen 7 9800X3D, NVIDIA GeForce RTX 5080, 32 GB
DDR5 (2 x 16 GB at 6000 MT/s), three NVMe SSDs, Windows 11 Pro 26200,
PowerShell collector in **quick** mode (no frame times, no sensors).

| Check | Result |
|---|---|
| Collector on a real PC | Ran as administrator in 4 s; wrote specs, events and disks; no warnings |
| Privacy | No computer name, user name, serial number or file name in any file (read in full, and searched for the owner's names) |
| Analyzer | Read every file with no notes; 16 checks passed, 11 had no data (quick mode) |
| What it reported | A disk I/O retry ("Disk 3", 25 October) and, minutes later in the log, a 0x9F DRIVER_POWER_STATE_FAILURE blue screen; the matching Kernel-Power 41 was rightly not counted as a power loss |
| Not yet known | Whether those findings are right: the owner has not confirmed what happened that day. Not an accuracy result |

Real hardware showed things the synthetic runs never did: both RAM modules
report the slot "DIMM 1" (the bank label tells channels apart), disk errors
name a Windows disk number the collector did not record, the stop-code text
had a double full stop, and the display reports 59 Hz (Windows' usual name
for a 60 Hz mode). Still missing: a 5-minute capture with PresentMon and
LibreHardwareMonitor.

### Second real run: a 5-minute capture (2026-11-15)

Same PC, PowerShell collector in **capture** mode, 300 samples at 1 per
second. Made with an older copy of the collector (before the disk-number and
bank-label fields), without PresentMon (Get-Tools.ps1 not run) and without
LibreHardwareMonitor, so: no frame times, no CPU temperature; sensors came
from Windows' counters and nvidia-smi.

| Check | Result |
|---|---|
| Collector | Finished the 300 s capture; both missing tools named in its warnings |
| Privacy | No computer name, user name or serial number in any file |
| Analyzer | Read every file; the same disk-retry and 0x9F findings as the first run (same events) |
| What the sensors show | An idle PC: GPU load median about 3% (max 68%), GPU 25-28 C, 18-52 W; CPU load average 7.5%; RAM about 68% in use |
| What it changed | "GPU-limited" and "CPU-limited performance" had reported "passed" on this idle capture. They now report no data, with a note saying the PC was idle (rules 2026.11.2) |

Still missing: a capture with PresentMon and LibreHardwareMonitor while a
game runs, with the current collector.

## Measured so far

Each of these was measured once, in the place named. They describe this
project's code, not real-world accuracy.

| Measure | Value | Context |
|---|---|---|
| Fuzzing: inputs run, crashes found and fixed | About 161,000 Python inputs in two long runs (80,485 and 80,704, 5,000 per property); 10 crash bugs found and fixed, each with a regression test; the second run, after the fixes, found none. Go `FuzzCleanRun`: 1,115,863 executions in 61 s, none found | Cloud build container (4 CPUs), Hypothesis 6.170.15, Go 1.24, 2026-11-14. Details: [fuzz/README.md](../fuzz/README.md) |
| Upload service memory for a zip bomb | Checking a 298 KB zip that unpacks to 300 MB allocated 775 MB before the fix and 1 MB after | `TestZipBombIsNotHeldInMemoryUnpacked`, cloud build container, 2026-11-14 |
| Photo reading time on a busy machine | About 40 s per photo before running Tesseract single-threaded, about 0.2 s after (one 1280x720 test image, 3 tries each) | Cloud build container, 4 CPUs at load ~13 from other jobs, 2026-11-14. Not a benchmark: it shows the thread setting mattered |
| Fault types detected | 29 | rules version 2026.11.2 |

## Plumbing checks - not results

Numbers from synthetic data or from the build container only prove that a
pipeline runs. They are recorded so a later real result has something to be
compared with, and must never be quoted as accuracy or speed.

| What | Number | Why it is not a result |
|---|---|---|
| Frame-time model vs. stutter rule, synthetic held-out set | Model caught 123 of 123 stutter windows with 3 of 333 false alarms; the rule caught 122 of 123 with 3 of 333 | Synthetic data, labeled by the same generator; 2026-11-14 |
| Frame-time model latency | PyTorch 0.24 ms (batch 1) and 35 ms (batch 256); ONNX Runtime 0.11 ms and 25 ms; CPU, 2 threads | A shared cloud VM with other jobs running; timings were noisy |
| LED reader, synthetic photos | 117 of 300 right, 11 wrong, 172 "not sure" (threshold 0.8) | Synthetic drawings, undertrained; 2026-11-14 |
| Photo reader, drawn screens | 28 of 31 codes read, 0 wrong, 0 of 9 invented | Generated images, not phone photos |

## To track as the project grows

| Measure | Value | Context (set, size, machine, date) |
|---|---|---|
| Real users / runs uploaded per week | | `GET /api/stats` -> `runs_by_week` |
| Diagnosis accuracy on the labeled fault set | | `python eval/run_eval.py --real-only`; record the number of cases |
| ... before / after each rule change | | |
| Photo read rate on real photos | | `python eval/photo_eval.py`; record how many photos |
| Model accuracy vs. rules engine, same set (Phase 5) | | `ml/frames/evaluate.py --real-only` |
| Model speed on CPU and GPU, PyTorch and ONNX Runtime (Phase 8) | | `ml/frames/benchmark.py`; name the machine and batch size |
| Collector overhead, Rust vs. PowerShell (Phase 6) | | name the PC and game; `collector-rs/README.md` says how |
| Streaming ingest rate and DuckDB query time (Phase 6) | | name the dataset size and machine |
| k6 load test: throughput and error rate (Phase 3) | | at a stated load; `deploy/loadtest/` |
| Upload-to-diagnosis time (Phase 3) | | from Prometheus |
| Sensor node: sample rate and UDP packet loss (Phase 7) | | `sensor-node/receiver` summary |
| Fuzzing: inputs run, crashes found and fixed (Phase 9) | see above | keep adding runs |
