# Measured results

Numbers for the resume go here - and only numbers that were measured, with
their context (which test set, how many cases, which machine). Nothing in this
file is an estimate. An empty row is honest; a guessed number is not.

When something here is measured, add it to the Application Helper project's
master reference too.

## What is verified today (2026-11-11)

These are test results, not accuracy claims.

| Check | Result |
|---|---|
| Analysis package unit tests | 116 pass (Python 3.11 and 3.13) |
| API tests | 57 pass on SQLite and on PostgreSQL 16 |
| Collector on real Windows (GitHub runner, Windows Server 2025) | Lint clean; unit tests pass on Windows PowerShell 5.1 and PowerShell 7; quick run and capture run complete; output contains no computer name, user name or serial number; the analyzer reads it |
| Fault types the rules engine can detect | 29 (`pcdoctor-analyze rules`) |
| Synthetic sample runs | 8 of 8 get their expected diagnosis - a plumbing check only; the rules were written against these |

**Not verified yet:** frame-time capture on a PC with a real game and a real
display (the test machine is a headless virtual machine, so PresentMon ran but
had nothing to record), LibreHardwareMonitor readings on real hardware, and
diagnosis accuracy on real faults. Those need Phase 1's "test on my own PC".

## To track as the project grows

| Measure | Value | Context (set, size, machine, date) |
|---|---|---|
| Real users / runs uploaded per week | | `GET /api/stats` -> `runs_by_week` |
| Diagnosis accuracy on the labeled fault set | | `python eval/run_eval.py --real-only`; record the number of cases |
| ... before / after each rule change | | |
| Model accuracy vs. rules engine, same set (Phase 3) | | |
| Model speed on CPU and on GPU (Phase 3) | | name the machine |
| Upload-to-diagnosis time (Phase 4) | | from Prometheus |
| Fault types detected | 29 | rules version 2026.11.1 |
