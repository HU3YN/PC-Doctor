# PC Doctor: state and plan

This file is the handoff between work sessions. To continue, start a session
on this repository and say: "Read docs/plan.md and carry out 'Plan for the next
session', starting at Step 0."

## Where things stand (2026-11-14, branch `claude/dreamy-bohr-fser6e`)

Every phase of [the roadmap](roadmap.md) now has code that passes its tests
in CI. Almost none of it has met real hardware, real photos, real accounts or
a real server: [testing.md](testing.md) lists exactly what only the owner can
check, and [results.md](results.md) is still the only place for measured
numbers.

### Done in the session of 2026-11-14

| Step | What was done |
|---|---|
| 0 | CI green on the starting commit; all local suites passed |
| 1 (Phase 4) | Sign-in, member and Account pages checked in a browser (sign-in wording and phone header fixed); OAuth, webhook and bot variables passed through Docker Compose and listed in `.env.example`; `PCDOCTOR_BOT_TOKEN` gives the bot its own upload limit and reads nothing; privacy page covers sign-in, members, webhook and bot |
| 2 (Phase 9) | `fuzz/` finished: 10 crash bugs found and fixed with regression tests; ~161,000 inputs measured; `docs/threat-model.md`; `SECURITY.md`; Dependabot; `security.yml` (pip-audit, npm audit, govulncheck, gitleaks, fuzzing), which found Go 1.26.0 standard-library vulnerabilities (fixed: toolchain go1.26.11) |
| Threat-model fixes | A duplicate upload no longer breaks the first link (`share_keys` table); webhook text escaped; uploads and OCR off the event loop; set-up rate-limited, longer code, one master enforced by the database; rate limits count the real caller behind two proxies (`PCDOCTOR_PROXY_HOPS`); the Go upload service no longer holds uploads unpacked in memory |
| Photo reader | A bezel or a 2 degree tilt no longer hides the text (crop to the screen); Tesseract single-threaded (~40 s to ~0.2 s per photo on a busy machine) |
| 3 (Phase 7) | SHT31 test fixed (the expected values were wrong; the datasheet agrees with the code); `sensor-node/receiver`; README; CI job |
| 4 (Phases 5, 8) | `ml/frames`: dataset split by series, CNN, training, evaluation against the real stutter rule, ONNX export, benchmark; CPU CI job |
| 5 (Phase 6) | `collector-rs` (Rust capture collector, Linux and Windows CI); live streaming end to end (API, Live page, `--live-url`); DuckDB build comparison on the run page |
| 6 (Phase 10) | `eval/photo_eval.py` runs and is tested; `ml/leds` debug-LED classifier (not wired into the API) |
| 7 | README, roadmap, results, new `testing.md`, `ml/` and `eval/` READMEs, this file |

### Known gaps in what was built

- The Rust collector has no Windows performance-counter or `nvidia-smi`
  fallback when LibreHardwareMonitor is not running (the PowerShell one has).
- The live-session batch limit is counted per API process even with Redis.
- A member who uploads a file that is already stored gets a working private
  link, but the run does not appear under "My runs" (it already has an owner,
  or none). Decide whether that is right.
- The LED model is undertrained even on synthetic data (117 of 300 right,
  172 "not sure"); it needs real photos, not tuning.
- `ml/frames` labels "stutter" against the generator's known base frame time;
  whether that matches what players feel is an assumption.

## Plan for the next session (execute in this order)

Rules for whoever executes this: the project rules at the bottom apply.
Commit and push after each step; after each push read the CI result (both
`ci` and `security` workflows) and fix failures before going on. Never write a
number into `docs/results.md` or a README unless it was measured, and say
where. Helper agents may be used for self-contained folders, but tell each to
leave committing to the main session, so nothing is lost if one is cut off by
a usage limit (this happened once on 2026-11-14 and no work was lost because
of that rule).

### Step 0 - Confirm the starting point

1. `git pull`; check that the latest `ci` and `security` runs passed,
   including the two `rust capture collector` jobs.
2. Set up as in [testing.md](testing.md) and run `pytest workers -q`,
   `pytest api -q`, `npm --prefix web test`, `go test ./...` in
   `upload-service/`, `cargo test` in `collector-rs/`.

### Step 1 - Close the remaining threat-model items (section 4)

In this order, each with a test:

1. **#2** `PCDoctorCollector.psm1:Find-PCDoctorPresentMon`: check the pinned
   SHA-256 and Intel's signature before running PresentMon; drop the `PATH`
   fallback for PresentMon and `nvidia-smi` when elevated. Pester tests run
   on real Windows in CI.
2. **#12** `Collect-PCDoctor.ps1`: validate the returned `share_key` and do
   not open the browser from the elevated process (print the link instead).
3. **#16** `services/photo.py`: accept only JPEG, PNG and WebP, and make the
   decompression-bomb warning an error.
4. **#17** refuse a non-HTTPS `PCDOCTOR_PUBLIC_URL` for a non-local host.
5. **#18** make the Redis rate-limit counter atomic (Python and Go).
6. **#10, #14** Redis password in the scale stack and k8s; refuse the default
   metrics token when the API is not on localhost.
7. **#13** security headers and a CSP in `web/nginx.conf` (check the
   dashboard still works in a browser).
8. **#1** section 5: a tag-triggered release workflow that builds the
   collector zip reproducibly, attests it (`actions/attest-build-provenance`)
   and publishes the SHA-256; `/api/collector.zip` serves the same bytes.

### Step 2 - Smaller follow-ups

1. Share the live-session batch limit through Redis.
2. Decide the member duplicate-upload behaviour (above) and test it.
3. Rust collector: the Windows performance-counter fallback, matching the
   PowerShell collector's `sensors.csv` columns.

### Step 3 - Help the owner test on real hardware

Not code: walk through [testing.md](testing.md#what-only-the-owner-can-prove)
with the owner, in the order there. Record every measurement in
[results.md](results.md) with its context, and fix what real hardware shows.

## Rules for the project

- **Read-only.** The collector never changes settings, installs drivers or runs fixes.
- **No personal data.** No file names, user names, serial numbers or browser data; no customer names anywhere.
- **Never commit secrets.** Keys and tokens go in git-ignored `.env` files.
- **Do not expose the app to the internet without HTTPS.**
- **Only measured results go in `docs/results.md`**, with their context.
- **Safe fault testing only**; **fuzz only this project's code on your own machines**; **low-voltage parts only** for the sensor node; **moderator approval** before the bot joins a server.
