# PC Doctor: state and plan

This file is the handoff between work sessions. To continue, start a session
on this repository and say: "Read docs/plan.md and carry out 'Plan for the next
session', starting at Step 0."

## Where things stand (2026-11-15, merged into the default branch `claude/festive-cray-nw5hzp`)

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

### Done in the second session of 2026-11-14 (the plan's Steps 0-2)

| Item | What was done |
|---|---|
| Threat model #2 | The collector runs PresentMon and nvidia-smi only with a valid Intel / NVIDIA signature, and skips the PATH when elevated; the server ships only the pinned PresentMon |
| #12 | The collector builds the result link only from well-formed parts and never opens a browser from an administrator window |
| #16 | Photos: JPEG, PNG and WebP only; images over the pixel limit refused |
| #17 | Discord/Google sign-in off unless the public address is HTTPS (or local/private) |
| #18 | Redis rate-limit counters get their expiry in the same transaction (Python and Go) |
| #10, #14 | Redis password (Compose scale stack and k3s); no default secrets; weak metrics tokens refused |
| #13 | Security headers and a strict CSP from the API and nginx, checked in a browser |
| #1 | Reproducible collector zip, a release workflow that attests and publishes it, the hash on the Get page; PresentMon a separate download |
| Step 2 | Live batch limit shared through Redis; members see a run they uploaded even if someone uploaded the file first; the Rust collector falls back to Windows' counters |

### Done on 2026-11-15 (the plan's Step 2 and 3)

| Item | What was done |
|---|---|
| #11 | "Sign out everywhere" and a master password change (Account page, checked in a browser) |
| #19 | Keys and tokens replaced with placeholders in the API's and nginx's access logs (checked with a running server and nginx 1.24) |
| #10 | k3s NetworkPolicies: only the app's pods reach PostgreSQL and Redis; a CI job schema-checks every manifest |
| #3 | [lan-https.md](lan-https.md): HTTPS with a local certificate authority on a shared network (not tried end to end) |
| #15 | The API image installs from a hashed lock file (`api/lock.py`); every image pinned by digest |
| nvidia-smi | The Rust collector reads an NVIDIA card through System32's nvidia-smi when it is signed by NVIDIA. CI on real Windows found the check failing when started from PowerShell 7 (inherited `PSModulePath`); fixed and tested against catalog-signed notepad.exe |

### Done on 2026-11-15, second part (the first real run)

| Item | What was done |
|---|---|
| Real run | The owner's PC, quick mode: collector clean, no personal data, analyzer read everything (results.md, "First run on real hardware") |
| Analysis | Double full stop in stop-code summaries fixed (test over every code); a disk error followed within 30 minutes by a blue-screen record is called "possibly one incident" in both findings (hedged: the record's time is the restart); disk errors name the drive from its Windows disk number |
| Collector | Records each disk's Windows number and each RAM module's bank (channel) label - passed on the real Windows runner |
| #11 | The master can revoke a single private link or phone photo link (run page, Photos page) |
| Fix | `open_photo` no longer changes Pillow's process-wide pixel limit |

### Done on 2026-11-15, third part (the first real capture)

The owner attached a 5-minute capture. It was made with an older copy of the
collector, without PresentMon and without LibreHardwareMonitor, and with no
game running (GPU load median 3%). It showed that "GPU-limited" and
"CPU-limited" reported "passed" on an idle PC; they now report no data with
a note saying the PC was idle (rules 2026.11.2). Recorded in results.md.

### Known gaps

- The owner's PC has run a quick check and an idle capture. A capture with
  the **current** collector, PresentMon and LibreHardwareMonitor, while a
  game is being played, is still missing. The owner's PC is not
  offered to cloud sessions, so runs come as zips attached to the chat.
- The first real run's findings (disk retry on "Disk 3", 0x9F blue screen,
  25 October) are not confirmed by the owner.
- The release workflow has never run (needs a `collector-v*` tag).
- The API image fetches the build backend for this repository's own two
  packages without a hash; nginx's error log can still show a full request
  line when the API is down.
- The LED model needs real photos; the frame-time model needs real cases.

## Plan for the next session (execute in this order)

Rules for whoever executes this: the project rules at the bottom apply.
Commit and push after each step; after each push read the CI result (both
`ci` and `security` workflows) and fix failures before going on. Pushing
again cancels a running CI run. Never write a number into `docs/results.md`
or a README unless it was measured, and say where. A local Windows-target
check of `collector-rs` without TLS rewrites `Cargo.lock`: restore it before
committing. Never squash or rebase merged history: `.gitleaksignore` allows
three findings by commit SHA.

### Step 0 - Confirm the starting point, and ask the owner

1. `git pull`; check that the latest `ci` and `security` runs passed. The
   merge on 2026-11-15 turned on the weekly security run and Dependabot:
   expect a first batch of Dependabot pull requests; review them, do not
   merge them blindly.
2. **Ask the owner what else they want changed.** On 2026-11-15 they said
   they want to "change some things around" without saying what. Write the
   answers into this file before starting Step 1.

### Step 1 - Convenience first: one download, frames and temperatures included

**The owner's requirement (2026-11-15):** the person checking a PC must not
have to download, install or start any other program to get frame times and
temperatures. One download, double-click, and the capture has everything.
Today it needs `Get-Tools.ps1` (PresentMon) and a separately started
LibreHardwareMonitor with its web server on - the owner's own capture missed
both. The two halves are not equally easy:

**Frames (PresentMon) - straightforward.**
1. Bundle the pinned PresentMon in the collector zip and in the release. This
   reverses the 2026-11-15 decision to make it a separate download. Its
   licence allows it: PresentMon's LICENSE.txt is a permissive MIT-style
   licence (Copyright Intel) - ship that file with it.
2. The release workflow fetches PresentMon and checks the pinned SHA-256, so
   the zip stays reproducible and attestable; `collector_build.py` and
   `/api/collector.zip` include it the same way. Keep the Intel signature
   check at run time (`Find-PCDoctorPresentMon`).
3. The collector picks the game itself (the busiest presenting program) and
   checks **at the start** that something is under load - warn and wait,
   instead of reporting an idle PC after 5 minutes.

**Temperatures - one decision for the owner first.**
- GPU temperature already works with nothing extra on NVIDIA (signed
  nvidia-smi; proven on the owner's capture). AMD and Intel GPUs: check what
  Windows or the vendor driver exposes without a kernel driver.
- **CPU temperature needs ring-0 access**, which Windows does not offer to a
  plain program. The project rule says the collector "never installs
  drivers", and Get-Tools.ps1 leaves LibreHardwareMonitor out for exactly
  that reason. Present these options and get the owner's decision before
  writing code - do not quietly change the rule:
  1. **Recommended:** bundle LibreHardwareMonitorLib (MPL-2.0 - redistribution
     is allowed; ship its licence and say where its source is) and load it
     from the collector only during a capture, as administrator, after a
     clear prompt ("PC Doctor will load a temporary hardware-monitoring
     driver to read temperatures; it is removed when the capture ends").
     Amend the read-only rule to allow exactly that, nothing else.
  2. Keep the rule: no CPU temperature without the user starting a tool
     (today's behaviour, with better prompts).
  3. Use only what Windows offers without a driver (ACPI thermal zones):
     usually not the CPU's real temperature - say so if used.
- **Research before building option 1** (do not rely on memory): which
  driver current LibreHardwareMonitor releases load, whether it is signed,
  whether Microsoft Defender or the vulnerable-driver blocklist flags it,
  how it is unloaded, and test it on the owner's PC first (an attached run).
- When it is built, update together: README, collector/README.md,
  docs/privacy.md, docs/rules.md (the rule), threat-model items #1 and #2,
  docs/testing.md, the Get page text, the release workflow and the Windows
  CI job.

### Step 2 - The owner's hardware (needs the owner)

1. Ask the three questions about the first run: is the monitor really
   60 Hz (Windows reports 59 Hz)? Was a USB drive or card reader attached on
   25 October? Did the blue screen happen around sleep or shutdown? With
   answers and the owner's yes, make it the first real case in `eval/cases/`
   (the raw zip is not committed without that yes; it is in the owner's
   `collector\runs` folder).
2. Next capture: with the current default branch, a game running, and
   (after Step 1) nothing else to start.
3. First look at the new `memory.modules[].bank` values: if they tell the
   two channels apart (e.g. "P0 CHANNEL A" / "P0 CHANNEL B"), extend
   `memory.single_channel` to flag sticks on one channel (wrong slots). Do
   not write that rule before seeing real labels. Check
   `physical_disks[].number` too.
4. Analyze with `pcdoctor-analyze`, compare with the real PC, fix what real
   hardware shows, record measurements in results.md.

### Step 3 - With the owner's yes

1. Push `collector-v1.0.0` (after Step 1, so the release includes
   PresentMon) and check it with `gh attestation verify`.
2. The owner turns on private vulnerability reporting (Settings > Code
   security).

### Step 4 - Small follow-ups

1. After real cases exist: retrain `ml/frames` and compare with the rule.

## Rules for the project

- **Read-only.** The collector never changes settings, installs drivers or runs fixes.
- **No personal data.** No file names, user names, serial numbers or browser data; no customer names anywhere.
- **Never commit secrets.** Keys and tokens go in git-ignored `.env` files.
- **Do not expose the app to the internet without HTTPS.**
- **Only measured results go in `docs/results.md`**, with their context.
- **Safe fault testing only**; **fuzz only this project's code on your own machines**; **low-voltage parts only** for the sensor node; **moderator approval** before the bot joins a server.
