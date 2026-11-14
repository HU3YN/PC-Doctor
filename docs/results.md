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
| API tests | 209 pass on SQLite and on PostgreSQL 16, including access control: every API route is checked to be master-only, signed-in-only or deliberately public |
| Dashboard unit tests | 6 pass; lint and type check clean |
| Sign-in pages, member view, Account page, Live page, build comparison | Driven in a real browser (Playwright, desktop and phone sizes) with stand-in Discord/Google ids: no console errors, no sideways scrolling |
| Go upload service | 10 tests pass with the race detector; fuzzed in CI |
| Discord bot | 130 tests pass against a stand-in API. **Never run on a real Discord server** |
| Rust capture collector | 52 tests pass on Linux; builds and tests on windows-latest in CI; the analyzer reads its output with no notes. **Never run with a real game** |
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

## Measured so far

Each of these was measured once, in the place named. They describe this
project's code, not real-world accuracy.

| Measure | Value | Context |
|---|---|---|
| Fuzzing: inputs run, crashes found and fixed | About 161,000 Python inputs in two long runs (80,485 and 80,704, 5,000 per property); 10 crash bugs found and fixed, each with a regression test; the second run, after the fixes, found none. Go `FuzzCleanRun`: 1,115,863 executions in 61 s, none found | Cloud build container (4 CPUs), Hypothesis 6.170.15, Go 1.24, 2026-11-14. Details: [fuzz/README.md](../fuzz/README.md) |
| Upload service memory for a zip bomb | Checking a 298 KB zip that unpacks to 300 MB allocated 775 MB before the fix and 1 MB after | `TestZipBombIsNotHeldInMemoryUnpacked`, cloud build container, 2026-11-14 |
| Photo reading time on a busy machine | About 40 s per photo before running Tesseract single-threaded, about 0.2 s after (one 1280x720 test image, 3 tries each) | Cloud build container, 4 CPUs at load ~13 from other jobs, 2026-11-14. Not a benchmark: it shows the thread setting mattered |
| Fault types detected | 29 | rules version 2026.11.1 |

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
