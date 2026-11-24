# PC Doctor: state and plan

This file is the handoff between work sessions. To continue, start a session
on this repository and say: "Read docs/plan.md and carry out 'Plan for the next
session', starting at Step 0."

## Where things stand (2026-11-24)

The default branch `claude/festive-cray-nw5hzp` holds everything up to
2026-11-15 plus the 2026-11-17 plan update. The code of 2026-11-17 and
2026-11-24 is on `claude/epic-archimedes-peiqrm`, CI green, **not merged
yet** (the owner merges).

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

### Done on 2026-11-17 (the plan's Step 0 and the first half of Step 1)

| Item | What was done |
|---|---|
| Step 0 | The default branch's last `ci` and `security` push runs passed. Since the first Dependabot batch (2026-11-15, 13 pull requests) **GitHub Actions has not started a single job**: every run fails within seconds and has no log, the scheduled security run included. The reason shows only on the run's page (owner to look; usually the account's Actions minutes or spending limit) |
| CI | Dependabot branches ran both workflows twice (push and pull_request): the push trigger skips `dependabot/**`; action updates come as one grouped pull request |
| Dependabot | All 13 pull requests read, none merged: see "Dependabot pull requests" below |
| Owner's decisions | CPU temperature: **prompted install, then remove** (below). Other changes: none named yet |
| Frames | PresentMon is in the collector zip (release and server), with Intel's licence; the separate download is gone. A copy without it (git) fetches and checks it at the first capture |
| Load check | A capture first checks that something is under load (GPU 30% or CPU 50%, three readings), waits up to 3 minutes for a game, and records `capture.load_at_start` |
| CPU temperature | Researched and prepared, not built: `collector/tests/Probe-CpuTemperature.ps1` for the owner's PC |

**None of this has run on Windows.** With Actions down, the PowerShell was
checked with Pester and PSScriptAnalyzer on PowerShell 7 for Linux (the
Windows-only tests cannot pass there); the Python and web suites ran locally.

#### CPU temperature: what the research found (2026-11-17)

- LibreHardwareMonitor no longer loads a temporary driver. From 0.9.5 on
  (latest stable 0.9.6, February 2026) it needs **PawnIO**, a separate kernel
  driver that is installed on the PC and stays. The driver it used before,
  WinRing0, is the one Microsoft Defender flags as vulnerable, so an old
  LibreHardwareMonitor is not an option.
- Read from PawnIO's official installer itself (2.2.0.0, SHA-256
  `1F519A22...FBA3032`, from github.com/namazso/PawnIO.Setup): it is signed
  by its author (namazso.eu, GLOBALTRUST code-signing certificate); it has
  `-install`, `-uninstall` and `-silent`; it says "This installer can be
  redistributed unmodified"; it needs Windows 10 1809 or later; it refuses to
  install over an existing installation. The driver is GPL-2.0.
- **Not known yet:** who signed the driver file it installs (it is packed
  inside the installer), whether Memory Integrity and the vulnerable-driver
  blocklist accept it, whether Defender or anti-cheat react, whether the
  uninstall is complete, and whether LibreHardwareMonitorLib loads in Windows
  PowerShell 5.1. pawnio.eu was not reachable from the session. The probe
  answers these on the owner's PC.
- **The owner's decision (2026-11-17):** bundle the PawnIO installer and
  LibreHardwareMonitorLib; during a capture, after a clear yes/no question,
  install PawnIO, read temperatures, and uninstall it when the capture ends;
  amend the read-only rule for exactly that. If PawnIO is already on the PC,
  use it and leave it there. If the probe shows a bad signature, a block, or
  an unclean uninstall, go back to the owner before building.

#### Dependabot pull requests (read 2026-11-17, none has a CI result)

Every image bump keeps its digest pin and the action SHAs match their tags.
- Wait for the grouped actions pull request instead of merging #4, #7, #9,
  #11, #12 one by one (it appears once this branch is on the default branch).
- Merge when CI is green: #6 nginx 1.29, #2 Go 1.27 (build stage), #3 Node
  26 (build stage), #5 Redis 8 (its volume cannot go back to 7).
- Test the scale stack locally first: #8 Prometheus 3, #10 Grafana 13 (CI
  does not check alerts or the dashboard; `deploy/k8s` stays on the old
  versions and would need the same change).
- Hold: #1 Python 3.15 (CI tests 3.11 and 3.13 only; PyYAML 6.0.3 has no
  3.15 wheel; `api/lock.py` and the CI matrix would have to move too).
- Close: #13 (TypeScript 7 is outside what the locked typescript-eslint
  accepts, `<6.1.0`); take the user-event patch separately.

### Done on 2026-11-24 (the rest of Step 1's frames half)

| Item | What was done |
|---|---|
| Actions | Running again (the block of 2026-11-15 to about 2026-11-22 lifted by itself or by the owner). Every `ci` and `security` job passed on the working branch, both Windows jobs included |
| Windows | The real Windows runner fetched PresentMon (SHA-256 and Intel signature checked), and the load check flagged the idle runner at the start ("GPU 14%, CPU 5%") and recorded it, without waiting (non-interactive) |
| Bundling | Finished and checked: the zip builds the same twice (SHA-256 `276d2861...` for this commit's collector), the API image fetches PresentMon, `Start-PCDoctor.ps1` fetches it without Docker. The Get page no longer claims a zip without PresentMon matches the release |
| Rust collector | `--start-presentmon` runs only a file with a valid Intel signature (`src/signature.rs`, shared with nvidia-smi); docs name the real file `PresentMon-2.6.0-x64.exe`. Not yet tried against the real PresentMon on Windows |
| Docs | collector README, README, privacy (the one github.com download), testing, roadmap, SECURITY; threat-model tables now agree with the fixed items (item #14 corrected: `POSTGRES_PASSWORD` still defaults to `pcdoctor`) |
| Dependabot | #13 was replaced by #17 (dev-tools, 7 updates), which fails: TypeScript 7 vs typescript-eslint 8 (`npm ci` ERESOLVE). Major TypeScript updates are now ignored; Dependabot should regroup #17 without it once this branch is on the default branch. New: #14-#16 (patch/minor web libraries) |

#### The PawnIO probe on GitHub's Windows runner (2026-11-24)

`windows-facts` job `pawnio-probe`, Windows Server 2025 (build 26100), AMD
EPYC VM, Secure Boot off, vulnerable-driver blocklist on:
- PawnIO 2.2.0.0 installed silently in about 1 s (exit code 0). Its driver
  `PawnIO.sys` (driver store `pawnio.inf`, published as `oemNN.inf`) is signed
  by **Microsoft Windows Hardware Compatibility Publisher**; the installer,
  `PawnIOLib.dll`, `PawnIOUtil.exe` and `uninstall.exe` by namazso.eu
  (GLOBALTRUST). The service ran. Defender: no detection.
- LibreHardwareMonitorLib 0.9.6 loaded in Windows PowerShell 5.1 and opened
  the CPU: sensor "Core (Tctl/Tdie)" read 0 C (a VM; a real Ryzen should give
  a value - only the owner's PC can show it).
- `uninstall -silent` (exit 0) removed the registration and the Program
  Files folder but **left the driver package and a stopped `PawnIO`
  service**. The probe (version 2) now removes those with pnputil and sc;
  its second run shows whether that leaves the PC clean.
- Not known: Memory Integrity (HVCI) on (the runner reported no value), a
  real CPU's temperature, anti-cheat games.

#### GPU temperature on AMD and Intel without a driver (research, 2026-11-24)

Not built. Best route found: `D3DKMTQueryAdapterInfo` with
`KMTQAITYPE_ADAPTERPERFDATA` (62) from gdi32.dll - Windows' own, WDDM 2.4+,
the same source windows_exporter says Task Manager uses. 64-byte
`D3DKMT_ADAPTER_PERFDATA`, `Temperature` (deci-Celsius) at offset 56 on x64
(from the Windows SDK 10.0.22621 `d3dkmthk.h`); adapter LUIDs from
`HKLM\SOFTWARE\Microsoft\DirectX\*`. Drivers that do not fill it give 0
(treat 0 or over 150 C as no reading). One third-party report of it working
on an RX 7900 XTX; nothing found for Intel. Fallbacks if it gives 0 on real
cards: AMD ADL (`atiadlxx.dll`, `ADL2_OverdriveN_Temperature_Get`), Intel
IGCL (`ControlLib.dll`, `ctlPowerTelemetryGet`) - both driver-installed,
both heavier. Needs a real AMD or Intel GPU to test; the owner's is NVIDIA.

### Done on 2026-11-24, second part (with the owner away from their PC)

| Item | What was done |
|---|---|
| Merge | The owner said "if it works then merge it": the default branch was fast-forwarded to the tested commit (94de33b), and again at the end of this part |
| First run, answered | 360 Hz monitor (Windows ran it at 59 Hz), USB-C drive attached, blue screen at shutdown (Step 2 below) |
| Displays | The collector records each screen's current, offered and EDID refresh rates (`specs.displays`); rule `display.refresh_below_max` (rules 2026.11.3, 30 rules) |
| USB drive | A disk error on a USB (or SD) drive says so, with checks for that; a USB disk error in the incident window of a 0x9F says a USB storage device failing to change power state is a common cause |
| CPU temperature | **Built as the owner decided.** The zip carries PawnIO's installer and LibreHardwareMonitorLib 0.9.6 with 13 libraries, all pinned (`collector/temperature-tools.json`) with licences in `collector/licences/`. A capture as administrator asks (default no), installs PawnIO, reads sensors in a separate Windows PowerShell 5.1 process, and removes the driver (also on Ctrl+C; a ProgramData marker lets the next run remove one left by a closed window) |
| Windows CI | The Windows job now installs PawnIO from the collector, reads through it and checks that nothing is left: passed. Three Windows PowerShell 5.1 problems were found and fixed on the way (a JSON array passed on as one object; `@()` around a generic list; one sensor group failing on a VM) |
| Rust collector | `--start-presentmon` checks Intel's signature |

### Done on 2026-11-24, third part

| Item | What was done |
|---|---|
| Dependabot | The owner said to merge the low-risk ones. Merged: #18 (all GitHub Actions, grouped), #2 (Go 1.27 build image), #19 (dev tools, without TypeScript 7), #20 (react-query), #15 (recharts) - each with all 20 checks green. #14 (react-router) waits for Dependabot's rebase; #6 (nginx 1.29) was brought up to date for a fresh CI run. Held: #1 (Python 3.15), #3 (Node 26), #5 (Redis 8, one-way volume), #8 (Prometheus 3), #10 (Grafana 13) - see "Dependabot pull requests" |
| GPU temperature, AMD and Intel | Windows' own adapter counters (D3DKMT `KMTQAITYPE_ADAPTERPERFDATA`) fill `gpu_temp_c` and `gpu_fan_rpm` when there is no nvidia-smi. On NVIDIA the collector logs both, for a cross-check on the owner's next capture ("GPU temperature cross-check" in collector.log). Unproven on real AMD and Intel drivers |
| Supply chain | The API image's build backend is now hashed; nginx's error log no longer prints key-bearing request lines when the API is down; `deploy/k8s` images pinned by Compose's digests (Dependabot does not watch them: bump by hand with Compose) |

### Done on 2026-11-24, fourth part

| Item | What was done |
|---|---|
| Dependabot | Also merged #6 (nginx 1.29) and #14 (react-router) after fresh green CI. The held five (#1 Python 3.15, #3 Node 26, #5 Redis 8, #8 Prometheus 3, #10 Grafana 13) were refreshed: all pass full CI. They stay for the owner to decide (not low-risk): #1 - the API tests never run on 3.15, only the image build and smoke test; #3, #5 - green, one-way volume for #5; #8 - the new rules/dashboard checks pass on it |
| CI | The docker job now checks that Prometheus loaded every alert rule (waiting for the first evaluation) and that Grafana provisioned the PC Doctor dashboard |
| Overhead | Every capture records `capture.overhead` (CPU and memory of the collector, PresentMon and the temperature reader) - Phase 6's number comes from the owner's next capture |
| Cases | `eval/make_case.py` turns a run zip into a labeled case in one command (eval/README.md has the command for the 25 October run) |
| Release | The release workflow ran as a manual dry run (no release published): fetch, build, SHA-256 and attestation all worked; a local rebuild of the same commit gave the same SHA-256 (`4e093d64...`), and the stored attestation names this repository, the workflow and the commit. A `collector-v` tag now fails unless it matches `$script:CollectorVersion`, which is still 0.1.0: bump it as part of the release |

### Known gaps
- **CPU temperature on real hardware is unproven:** the VM reports 0 C. The
  owner's next capture (answer y at the prompt) is the test; Memory
  Integrity on and anti-cheat games are untested.
- The working branch is not merged, so Dependabot still reads the old
  `dependabot.yml` (no actions group, TypeScript 7 not ignored).

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

### Step 0 - Confirm the starting point

1. `git pull`; check the latest `ci` and `security` runs. If runs fail
   within seconds with no log, Actions is blocked again (as from 2026-11-15
   to about 2026-11-22): tell the owner, test locally meanwhile, and say in
   each commit what was and was not run.
2. Ask the owner to merge `claude/epic-archimedes-peiqrm` into the default
   branch (CI green on 2026-11-24), so Dependabot picks up its new config.
3. Dependabot: follow the list under "Dependabot pull requests" above; #14,
   #15, #16 are patch/minor web updates (merge when green); #17 should come
   back without TypeScript 7.
4. Ask the owner whether there is anything else to change (asked on
   2026-11-17; the answer was the CPU temperature decision only).

### Step 1 - Convenience: what is left

**The owner's requirement (2026-11-15):** the person checking a PC must not
have to download, install or start any other program to get frame times and
temperatures. One download, double-click, and the capture has everything.

Frames are done (2026-11-17): PresentMon is in the zip, the game is picked
after the capture (the busiest presenting program), and the capture waits
for load at the start. Left:

1. **Built (2026-11-24).** What is left needs the owner's PC: a capture
   with a game running, answering y to the driver question. Check
   `sensors.csv` `cpu_temp_c` is real (a Ryzen 7 9800X3D at load: tens of
   degrees, not 0), `capture.temperature_driver.removed` is true, and
   Settings > Apps shows no PawnIO afterwards. If Memory Integrity is on
   (Windows Security > Device security > Core isolation), say so. The probe
   script (`collector/tests/Probe-CpuTemperature.ps1`) is no longer needed
   unless the capture fails. The owner runs
   `collector\tests\Probe-CpuTemperature.ps1` in an administrator PowerShell
   and attaches `collector\runs\cpu-temperature-probe.json`. Read in it:
   the installed driver's signer and status, `protections`, `reading.error`
   and the temperature sensor names, `leftovers.clean`, `defender`.
2. **If the probe is clean, build it** as the owner decided (see "CPU
   temperature: what the research found"):
   - Bundle `PawnIO_setup.exe` (unmodified, pinned SHA-256, its GPL-2.0
     licence text and where the source is) and LibreHardwareMonitorLib 0.9.6
     with the libraries the probe lists (MPL-2.0 and MIT: ship the licences),
     fetched and hash-checked by `collector_build.py` like PresentMon.
   - In a capture, as administrator, when LibreHardwareMonitor's web server
     is not answering: ask ("PC Doctor can install a hardware-monitoring
     driver (PawnIO) to read the CPU temperature and remove it when the
     capture ends. Install it? [y/N]"), default no, never in
     `-NonInteractive` without an explicit switch. Check the installer's
     signature before running it. Uninstall in a `finally`, and also when
     the window is closed mid-capture if that can be done; say plainly at
     the end whether the driver is gone. PawnIO already installed: use it,
     never remove it.
   - Read sensors in the collector's own process only if the probe shows
     the libraries load in Windows PowerShell 5.1; `sensors.source` gets a
     new value (document it in run-format.md, teach the analyzer).
   - Record in the manifest that a driver was installed and removed.
   - The Rust collector is not part of this.
3. **If the probe is not clean** (driver not signed by Microsoft or blocked,
   Defender detection, leftovers, libraries do not load): stop and take the
   finding to the owner; the fallback they did not choose is "use PawnIO
   only if it is already installed".
4. AMD and Intel GPUs: researched (see "GPU temperature on AMD and Intel
   without a driver"); build the D3DKMT reader as a Windows-sample fallback
   when an AMD or Intel GPU is available to test on.
5. When it is built, update together: README, collector/README.md,
   docs/privacy.md, docs/rules.md and the rule at the bottom of this file,
   threat-model items #1 and #2, docs/testing.md, the Get page text, the
   release workflow and the Windows CI job.

### Step 2 - The owner's hardware (needs the owner)

1. **Answered by the owner (2026-11-24):** the monitor is **360 Hz** (so
   Windows running it at 59 Hz is a real fault - wrong setting or a cable or
   port that cannot carry 360 Hz; the collector now records the offered
   modes and rule `display.refresh_below_max` flags it); a **USB-C drive was
   attached** on 25 October (so "Disk 3" was most likely that drive, not an
   internal SSD); the blue screen happened **at shutdown** (0x9F
   DRIVER_POWER_STATE_FAILURE at shutdown fits a USB storage device or its
   driver failing to power down - consistent with "possibly one incident").
   Still to do: the owner re-attaches the first run's zip (in
   `collector\runs`) and says yes, then it becomes the first real case in
   `eval/cases/` with that label; check the next quick run names Disk 3 as
   the USB drive (`physical_disks[].number`, bus type). Consider teaching
   the disk and 0x9F findings that a removable USB disk is the likely cause
   when it is the disk named.
2. Next capture: with the current default branch and a game running.
   Frame times need nothing else now; after a quick run, check the new
   `displays` entry shows 59 Hz current and 360 Hz offered (or not - which
   tells setting from cable); until Step 1 is finished, CPU
   temperature still needs LibreHardwareMonitor started by hand.
3. First look at the new `memory.modules[].bank` values: if they tell the
   two channels apart (e.g. "P0 CHANNEL A" / "P0 CHANNEL B"), extend
   `memory.single_channel` to flag sticks on one channel (wrong slots). Do
   not write that rule before seeing real labels. Check
   `physical_disks[].number` too.
4. Analyze with `pcdoctor-analyze`, compare with the real PC, fix what real
   hardware shows, record measurements in results.md.

### Step 3 - With the owner's yes

1. Set `$script:CollectorVersion` to 1.0.0 (the release job checks the tag
   against it), push `collector-v1.0.0`, and check the release with
   `gh attestation verify` on the owner's PC (this session's network cannot
   reach Sigstore's trust root; the dry run of 2026-11-24 passed otherwise).
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
