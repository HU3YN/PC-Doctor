# PC Doctor: state and plan

This file is the handoff between work sessions. To continue, start a session
on this repository and say: "Read docs/plan.md and carry out 'Plan for the next
session', starting at Step 0."

## Where things stand (2026-11-14, evening, branch `claude/dreamy-bohr-fser6e`)

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

### Known gaps

- The release workflow has never run: it runs on a `collector-v*` tag.
- The Rust collector's Windows-counter fallback was compiled for Windows and
  tested in CI, never run on a real PC; it has no `nvidia-smi` (that needs a
  publisher signature check in Rust).
- Still open in the threat model: plain HTTP in LAN mode (#3), no session
  revocation or password change (#11), unpinned Python dependencies (#15),
  keys in access logs (#19), no NetworkPolicy in k3s (#10, part).
- The LED model needs real photos; the frame-time model needs real cases.

## Plan for the next session (execute in this order)

Rules for whoever executes this: the project rules at the bottom apply.
Commit and push after each step; after each push read the CI result (both
`ci` and `security` workflows) and fix failures before going on. Pushing
again cancels a running CI run, so wait for one to finish before the next
push when a step depends on it. Never write a number into `docs/results.md`
or a README unless it was measured, and say where.

### Step 0 - Confirm the starting point

`git pull`; check that the latest `ci` and `security` runs passed; run the
local suites as in [testing.md](testing.md).

### Step 1 - With the owner: real hardware first

The code is ahead of the evidence. Walk through
[testing.md](testing.md#what-only-the-owner-can-prove) with the owner, in
order, starting with a capture on their gaming PC. Fix what real hardware
shows, and record every measurement in [results.md](results.md) with its
context. Ask the owner before pushing the first `collector-v1.0.0` tag (it
publishes a release).

### Step 2 - Remaining threat-model items

1. **#11** a "sign out everywhere" button (delete the account's sessions) and
   a password change for the master, with tests.
2. **#15** a lock file for the Python dependencies (`pip-compile` or `uv
   lock`) used by the Dockerfiles; pin the base images by digest.
3. **#3** HTTPS on the LAN: document `mkcert` or a reverse proxy with a local
   certificate, or offer it from `Start-PCDoctor.ps1`.
4. **#10** a NetworkPolicy in `deploy/k8s` so only the API, worker and
   upload service reach Redis and PostgreSQL.
5. **#19** keep share keys and live tokens out of the access logs (log the
   route template, not the path).

### Step 3 - Smaller follow-ups

1. `nvidia-smi` in the Rust collector, after a signature check
   (`WinVerifyTrust` plus the signer's name).
2. After real cases exist: retrain `ml/frames`, and compare with the rule.

## Rules for the project

- **Read-only.** The collector never changes settings, installs drivers or runs fixes.
- **No personal data.** No file names, user names, serial numbers or browser data; no customer names anywhere.
- **Never commit secrets.** Keys and tokens go in git-ignored `.env` files.
- **Do not expose the app to the internet without HTTPS.**
- **Only measured results go in `docs/results.md`**, with their context.
- **Safe fault testing only**; **fuzz only this project's code on your own machines**; **low-voltage parts only** for the sensor node; **moderator approval** before the bot joins a server.
