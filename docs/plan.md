# PC Doctor: state and plan

This file is the handoff between work sessions. To continue, start a session
on this repository and say: "Read docs/plan.md and carry out 'Plan for the next
session', starting at Step 0."

## Where things stand (2026-11-15, branch `claude/dreamy-bohr-fser6e`)

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

### Known gaps

- Nothing has met the owner's hardware yet. The owner's PC (HueyPC) is in
  the Remote Control list, but it does not offer its folders to cloud
  sessions (likely the Claude app there needs updating), so the capture has
  to come from the owner: run the collector, attach the zip.
- The repository's default branch is still `claude/festive-cray-nw5hzp`:
  until this branch is merged there, the weekly security run, Dependabot and
  the manual release run are not active.
- The release workflow has never run (needs a `collector-v*` tag).
- Single links (a share key, a photo link) cannot be revoked on their own.
- The LED model needs real photos; the frame-time model needs real cases.

## Plan for the next session (execute in this order)

Rules for whoever executes this: the project rules at the bottom apply.
Commit and push after each step; after each push read the CI result (both
`ci` and `security` workflows) and fix failures before going on. Pushing
again cancels a running CI run. Never write a number into `docs/results.md`
or a README unless it was measured, and say where. A local Windows-target
check of `collector-rs` without TLS rewrites `Cargo.lock`: restore it before
committing.

### Step 0 - Confirm the starting point

`git pull`; check that the latest `ci` and `security` runs passed.

### Step 1 - The owner's hardware (needs the owner)

Either the owner's PC is offered to the session (`list_computer_folders`
shows it under `folders`), or the owner attaches a capture zip. Then: analyze
it with `pcdoctor-analyze`, compare with what the PC really is, fix what
real hardware shows, and record measurements in [results.md](results.md).
Then walk through the rest of [testing.md](testing.md#what-only-the-owner-can-prove).

### Step 2 - With the owner's yes

1. Merge this branch into the default branch (a pull request), so the
   weekly security run and Dependabot start.
2. Push `collector-v1.0.0` and check the release with `gh attestation verify`.
3. Turn on private vulnerability reporting (Settings > Code security).

### Step 3 - Small follow-ups

1. Revoke a single share key or photo link from the master's views.
2. After real cases exist: retrain `ml/frames` and compare with the rule.

## Rules for the project

- **Read-only.** The collector never changes settings, installs drivers or runs fixes.
- **No personal data.** No file names, user names, serial numbers or browser data; no customer names anywhere.
- **Never commit secrets.** Keys and tokens go in git-ignored `.env` files.
- **Do not expose the app to the internet without HTTPS.**
- **Only measured results go in `docs/results.md`**, with their context.
- **Safe fault testing only**; **fuzz only this project's code on your own machines**; **low-voltage parts only** for the sensor node; **moderator approval** before the bot joins a server.
