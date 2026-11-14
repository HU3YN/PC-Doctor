# PC Doctor: state and plan

This file is the handoff between work sessions. To continue, start a session
on this repository and say: "Read docs/plan.md and carry out 'Plan for the next
session', starting at Step 0."

## Where things stand (2026-11-14, branch `claude/festive-cray-nw5hzp`)

The handoff commit is the one that adds this file; `git log` shows it. Everything
below "Built and tested" passed its tests in the build environment. Nothing in
this file is a measured result: `docs/results.md` is still the only place for those.

### Built and tested

| Phase | What now exists | Tested how |
|---|---|---|
| 1 | Collector, 29-rule analysis, API, dashboard, start script (unchanged) | CI: Linux, PostgreSQL, Docker Compose, real Windows |
| 2 | AI troubleshooter: `POST /api/assist/troubleshoot`, a panel on the run page, `eval/agent_eval.py` to score it against the rules engine on the same cases. It may only cite findings the run really has | Against a stand-in. **Never against the real API** |
| 3 | `upload-service/` (Go) with the same limits as `ingest.py`; Redis queue; `python -m pcdoctor_api.worker`; Prometheus metrics on the API (token), worker and upload service; shared rate limits; `docker-compose.scale.yml` (adds Redis, worker, upload service, Prometheus, Grafana); `deploy/` with alerts, a Grafana dashboard, a k6 load test, Terraform and k3s manifests | Go tests and fuzzing; the whole queue path ran in Docker in CI, with Prometheus scraping all three. **Terraform and k3s: format/schema check only, never applied** |
| 4 | Sign-in with Discord or Google (authorization code flow with PKCE, hand-written in `api/pcdoctor_api/services/oauth.py`); member accounts that see only their own runs; master-only routes now check the role; Account page; Discord webhook on a new guest run; `bot/` Discord bot with `/diagnose` | 162 API tests on SQLite and PostgreSQL, 127 bot tests. **Never against real Discord or Google** |

Fixed along the way: tests that left database sessions open hung the PostgreSQL
CI job; a run file with a number thousands of digits long crashed the loader
(found by the new fuzz tests).

### Unfinished work that is committed (do not trust it yet)

| Folder | State |
|---|---|
| `sensor-node/firmware/` | Protocol code, SHT31 driver, firmware `main.cpp`, host tests. 23 of 24 host tests pass; `sht31_frame_datasheet_word_in_both_halves` fails (expected 8559/7459, got 8552/7458 - check the conversion rounding against the datasheet before changing the test). No receiver, no README |
| `fuzz/` | Hypothesis tests for the PresentMon, sensors, loader and error-text parsers. `test_fuzz_loader.py` calls `known_bugs.match_note`, which does not exist. No test for `ingest.unpack` yet, no README |
| `eval/photo_eval.py`, `eval/photos/` | Script written (496 lines), never run, no tests |
| `ml/frames/` | Only a `.gitignore` |

### Not started

Phase 5 (PyTorch model), Phase 6 (Rust collector, streaming, DuckDB build
comparison), Phase 8 (ONNX benchmark), the rest of Phase 9 (threat model,
`SECURITY.md`, Dependabot, security workflow), Phase 10 LED reader (`ml/leds/`),
and the docs update (README, roadmap, results, privacy, `.env.example`).

### Still not verified by anyone

A capture on a real gaming PC; LibreHardwareMonitor on real hardware; diagnosis
accuracy; photo reading on real phone photos; the AI helper and troubleshooter
against the real API; a real phone scanning the QR code; the start script's
Docker route on Windows; real Discord/Google sign-in; the bot on a real server;
Terraform and k3s on a real AWS account; k6 numbers on a real machine.

## Plan for the next session (execute in this order)

Rules for whoever executes this: the project rules at the bottom apply. Commit
and push after each step. After each push, read the CI result (GitHub Actions)
and fix failures before going on. Never write a number into `docs/results.md`
or a README unless it was measured, and say where. If a step cannot be verified
in the build environment, say so in that folder's README under "Not verified".
Work in the main session where possible: helper agents ran into the usage
limit twice and lost their work.

### Step 0 - Confirm the starting point

1. `git pull`, then check that CI passed for the latest commit. The `discord bot`
   job is new and has not run yet.
2. Set up: `python -m venv .venv && pip install -e "workers[dev]" -e "api[dev,ai]"`,
   `npm --prefix web ci`. Run `pytest workers api`, `npm --prefix web test`,
   `go test ./...` in `upload-service/`, `pytest` in `bot/`.

### Step 1 - Close out Phase 4

1. Drive the new pages in a real browser (Playwright is installed): sign-in
   page with a fake provider configured, member home, a member opening their own
   run, the Account page. Fix what looks wrong.
2. `docker-compose.yml`: pass the new variables through to the API
   (`PCDOCTOR_PUBLIC_URL`, the four OAuth variables, `PCDOCTOR_OAUTH_SIGNUP`,
   `PCDOCTOR_NOTIFY_WEBHOOK_URL`). Fix the stale comment "There are no logins yet".
3. `.env.example`: add every new variable with one line each (OAuth, webhook,
   `PCDOCTOR_REDIS_URL`, `PCDOCTOR_METRICS_TOKEN`, `GRAFANA_PASSWORD`).
4. The bot uploads as a guest, and guests are limited to 30 uploads an hour per
   address, so a busy server hits the limit. Decide and implement: a bot token
   (`PCDOCTOR_BOT_TOKEN`) that the API accepts for a higher limit - never a way
   to read anything.
5. `docs/privacy.md`: add what is stored for a Discord/Google sign-in (the
   provider's id only), what a member can see, and what the webhook sends.

### Step 2 - Phase 9 groundwork (finish `fuzz/` first: it finds real bugs)

1. Fix `fuzz/`: add or remove `match_note`; add Hypothesis tests for
   `api/pcdoctor_api/services/ingest.unpack` (random bytes; hostile zips: path
   traversal, absolute paths, backslashes, duplicate names, 201+ entries, a
   highly compressible entry against a small limit, the encrypted flag).
   Properties: only `UploadError` is raised, nothing is written outside the
   destination, only allow-listed names appear, the size limit holds.
2. Run the fuzz tests for several minutes. Every crash becomes a regression test
   in `workers/tests` or `api/tests` and gets fixed.
3. `fuzz/README.md`: what is fuzzed, short and long runs (Python and
   `go test -fuzz=FuzzCleanRun`), what to do with a crash, a table for "inputs
   run, crashes found and fixed".
4. `docs/threat-model.md`, written from the code: what is protected, who the
   actors are, each entry point with the mitigation that exists (file and
   function) and what is still open. Include a plan for signing the collector
   zip without a paid certificate (GitHub artifact attestations).
5. `SECURITY.md` (GitHub private vulnerability reporting; no invented email),
   `.github/dependabot.yml`, `.github/workflows/security.yml` (pip-audit, npm
   audit, govulncheck, a secret scan, the fuzz tests on a short budget).

### Step 3 - Phase 7, the sensor node

1. Resolve the failing SHT31 host test.
2. `sensor-node/receiver/`: standard-library Python. Listens on UDP, checks
   magic, version and CRC, tracks sequence numbers per node (loss, duplicates,
   reordering, wrap, reboot), writes `elapsed_s,case_temp_c,case_humidity_pct`
   to CSV, prints a summary (packets, lost, loss %, sample rate). A `--simulate`
   sender with optional loss. pytest tests, including one that parses a packet
   made by the compiled C encoder.
3. `sensor-node/README.md`: parts (low-voltage only, USB powered, never wired to
   the PC's internal headers), wiring, build and flash, how to measure loss and
   sample rate, "Not verified" (PlatformIO could not be reached, so the firmware
   has never been compiled for the ESP32).
4. CI job: host C tests and receiver tests.

### Step 4 - Phase 5 and 8, the model and the benchmark (`ml/frames/`)

1. `dataset.py`: frame-time windows labeled stutter/smooth from a synthetic
   generator (30-240 fps, isolated hitches, periodic spikes, bursts, pacing
   oscillation, hard negatives) and from real cases in `eval/cases/` (none yet;
   test that path with a fake case). Split by series, not by window.
2. `model.py` (small 1-D CNN), `train.py` (fixed seed, weights and a JSON model
   card under a git-ignored `out/`), `evaluate.py` (model and the real
   `performance.stutter` rule on the same held-out set; `--real-only`),
   `export_onnx.py` (checks ONNX Runtime matches PyTorch).
3. `benchmark.py`: PyTorch and ONNX Runtime, CPU and GPU when present, batch
   sizes 1/8/64/256, median and p95. The JSON names the machine by hardware
   only - never the computer name or user name.
4. Tests, README, CPU-only CI job. Numbers from synthetic data and from the
   build machine are plumbing checks and must be labeled that way.
   Note: `download.pytorch.org` is blocked in the build environment; PyPI works
   (the default Linux wheel is large - about 28 GB of disk was free).

### Step 5 - Phase 6: Rust collector, streaming, build comparison

1. `collector-rs/`: a `pcdoctor-capture` binary for the capture part only
   (frames and sensors). Tails the PresentMon CSV, keeps only the target
   process's rows (only a count of the others), samples LibreHardwareMonitor's
   `data.json`, writes `presentmon.csv`, `sensors.csv` and `manifest.json` in the
   existing run format, zips it, and reports its own CPU time and memory.
   Read-only. Logic in a library crate that tests on Linux; a Windows build and
   test job in CI. Check the output with `pcdoctor-analyze`.
2. Live streaming, both sides. Collector: batches of NDJSON to
   `POST /api/live/{token}/samples` about once a second - lines
   `{"type":"frame","t":s,"ms":x}`, `{"type":"sensor","t":s,"values":{...}}`,
   `{"type":"end"}`. HTTPS required except for localhost and private addresses.
   API: the master creates a live session (a token, like a photo link - it can
   only add samples), the samples go into a bounded buffer (Redis when
   configured), and a "Live" page polls it. Add the routes to the lists in
   `api/tests/test_auth.py`.
3. Build comparison with DuckDB: "among runs with the same GPU (and CPU), where
   does this run's average FPS, 1% low and peak temperatures sit?" An endpoint
   on the run, master only, and a section on the run page. Say how many runs
   the comparison rests on, and show nothing below a minimum.

### Step 6 - Phase 10: photo reader

1. Run `eval/photo_eval.py` with `--synthetic`, fix it, add tests in
   `eval/tests/`. It must report counts ("N of M"), count a wrong code
   separately from no code, and use the same code path as the server.
2. `ml/leds/`: dataset layout by class (none, cpu, dram, vga, boot), a small CNN
   from scratch, train/evaluate/predict with a "not sure" threshold, a split by
   board, a synthetic generator for plumbing only. Not wired into the API until
   it is measured on real photos.

### Step 7 - Documentation (do this last, in one pass)

1. `README.md`: the new parts, the layout table, how to run each.
2. `docs/roadmap.md`: the status table and the skills table, phase by phase.
   Keep the honest note: these phases were built by an assistant; a skill goes
   on a resume only when its owner can explain and change the code.
3. `docs/results.md`: update the test counts under "What is verified" with the
   date, and fix the phase numbers in the "To track" table (model rows are
   Phase 5 and 8, upload-to-diagnosis time is Phase 3). No estimates.
4. A new `docs/testing.md`: for every part, the command to run it and the
   command to test it, on Windows and Linux, and what only the owner's PC,
   phone or accounts can prove.
5. Folder READMEs that still say "not built yet" (`ml/`, `eval/`).

## How to run and test what exists today

On the master PC (Windows), after `git pull`:

| What | How |
|---|---|
| The app | Double-click `Start-PCDoctor.cmd`; type the setup code into the browser; "Load demo data" |
| Tests | `pip install -e "workers[dev]" -e "api[dev,ai]"`, then `pytest workers api`; `npm --prefix web test` |
| Sample diagnosis | `python eval/run_eval.py` |
| The queue path and monitoring | Docker Desktop running, then `docker compose -f docker-compose.yml -f docker-compose.scale.yml up -d --build`; see `deploy/README.md` |
| Go upload service | `cd upload-service && go test ./...` |
| Discord bot | `cd bot && pip install -e ".[dev]" && pytest`; set-up steps in `bot/README.md` |
| Discord/Google sign-in | `docs/oauth.md` |
| AI troubleshooter | Put `ANTHROPIC_API_KEY` in `.env`, set a spending cap, restart; "Ask the troubleshooter" on a run. Score it with `python eval/agent_eval.py --synthetic --limit 3` (each case is one paid call) |
| Cloud | `deploy/README.md` section 3. Needs an AWS account and a domain. HTTPS only |

The owner's own next steps are unchanged, and nothing above replaces them:
(1) run it on your own PC, (2) first real capture with PresentMon and
LibreHardwareMonitor, (3) the QR phone flow for real, (4) decide on the AI
helper, (5) start the labeled fault set, (6) cloud hosting.

## Rules for the project

- **Read-only.** The collector never changes settings, installs drivers or runs fixes.
- **No personal data.** No file names, user names, serial numbers or browser data; no customer names anywhere.
- **Never commit secrets.** Keys and tokens go in git-ignored `.env` files.
- **Do not expose the app to the internet without HTTPS.**
- **Ship phases in order.**
- **Only measured results go in `docs/results.md`**, with their context.
- **Safe fault testing only**; **fuzz only this project's code on your own machines**; **low-voltage parts only** for the sensor node; **moderator approval** before the bot joins a server.
