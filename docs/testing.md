# Running and testing each part

Every command runs from the repository root unless it says otherwise. On
Windows, use PowerShell; where a command differs, both are given. The last
section lists what only the owner's own PC, phone or accounts can prove - CI
cannot.

## One-time set-up

| | Linux / macOS | Windows |
|---|---|---|
| Python environment | `python3 -m venv .venv && . .venv/bin/activate` | `py -m venv .venv; .venv\Scripts\Activate.ps1` |
| Analysis, API, tests | `pip install -e "workers[dev]" -e "api[dev,ai]"` | same |
| Dashboard | `npm --prefix web ci` | same |
| Photo reading | `sudo apt-get install tesseract-ocr` | [UB-Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki) |

## The parts

| Part | Run it | Test it |
|---|---|---|
| Whole app | Windows: double-click `Start-PCDoctor.cmd`. Anywhere with Docker: `docker compose up -d --build`, then <http://localhost:8080> | `pytest api -q` and `pytest workers -q` (run them separately: they cannot share one pytest run) |
| Analysis only | `pcdoctor-analyze path\to\run-folder-or.zip` | `pytest workers -q`; `pcdoctor-analyze rules` |
| Dashboard (dev server) | `npm --prefix web run dev` (with the API on port 8000) | `npm --prefix web test`, `npm --prefix web run lint`, `npm --prefix web run typecheck` |
| Collector (PowerShell) | On the PC: double-click `collector\PCDoctor.cmd` | Windows only: `Invoke-Pester collector/tests` (Pester 5) |
| Queue path and monitoring | Set `REDIS_PASSWORD`, `PCDOCTOR_METRICS_TOKEN` and `GRAFANA_PASSWORD` in `.env`, then `docker compose -f docker-compose.yml -f docker-compose.scale.yml up -d --build`; see [deploy/README.md](../deploy/README.md) | CI's `docker compose` job does the same end to end |
| Go upload service | `cd upload-service && go run .` | `cd upload-service && go test -race ./...`; fuzz: `go test -run xxx -fuzz=FuzzCleanRun -fuzztime=60s .` |
| Load test | `k6 run deploy/loadtest/upload.js` (after `python deploy/loadtest/make_run.py`) | - |
| Discord bot | `cd bot && pip install -e ".[dev]"`, set its variables ([bot/README.md](../bot/README.md)), `python -m pcdoctor_bot` | `cd bot && python -m pytest -q` |
| Discord/Google sign-in | Set the variables in [oauth.md](oauth.md), restart | Covered by `pytest api` against a stand-in provider |
| AI troubleshooter | Put `ANTHROPIC_API_KEY` in `.env` (set a spending cap), restart, "Ask the troubleshooter" on a run | `python eval/agent_eval.py --synthetic --limit 3` (each case is one paid call) |
| Rust capture collector | `cd collector-rs && cargo build --release`, then on Windows: `target\release\pcdoctor-capture.exe --process Game.exe --start-presentmon ..\collector\tools\PresentMon.exe` | `cd collector-rs && cargo test`; `bash scripts/check-with-analyzer.sh` (Linux) |
| Live view | Dashboard > **Live** > Start, then add `--live-url <address>` to the Rust collector | `pytest api/tests/test_live.py -q`; `cargo test live` |
| Build comparison | A run's page, "Compared with the same build" (needs 5+ runs of the same card and game) | `pytest api/tests/test_compare.py -q` |
| Sensor node firmware | `cd sensor-node/firmware && pio run -t upload` ([README](../sensor-node/README.md)) | Host tests: `make -C sensor-node/firmware/test_host` (Linux, or Windows with MSYS2 make and gcc) |
| Sensor receiver | `cd sensor-node/receiver && python -m case_sensor` | `cd sensor-node/receiver && python -m pytest -q`; without hardware: `python -m case_sensor --simulate --loss 0.05` |
| Frame-time model and benchmark | `cd ml/frames`, then `python train.py`, `python evaluate.py`, `python export_onnx.py`, `python benchmark.py` ([README](../ml/frames/README.md)) | `cd ml/frames && python -m pytest -q` |
| Debug-LED reader | `cd ml/leds`, then `python train.py --data data`, `python predict.py photo.jpg` | `cd ml/leds && python -m pytest -q` |
| Diagnosis scoring | `python eval/run_eval.py` (`--real-only` once real cases exist) | - |
| Photo reader scoring | `python eval/photo_eval.py` (needs `eval/photos/labels.csv`); `--synthetic 40` for a plumbing check | `pytest eval/tests -q` |
| Fuzz tests | Long run: `PCDOCTOR_FUZZ_PROFILE=long pytest -c fuzz/pytest.ini fuzz` (Windows: `$env:PCDOCTOR_FUZZ_PROFILE="long"` first) | Short run: `pytest -c fuzz/pytest.ini fuzz` |
| Collector release | Push a tag: `git tag collector-v1.0.0 && git push origin collector-v1.0.0` (or "Run workflow" on `release collector` to build and attest without a release) | `gh attestation verify PCDoctor-collector.zip --repo HU3YN/PC-Doctor`; the zip's SHA-256 equals the one on the Get page of a server at the same commit (a server that has the pinned PresentMon, as the Docker image does) |
| Python lock file (Docker image) | After changing a dependency in `api/pyproject.toml`: `pip install uv && python api/lock.py`, commit `api/requirements.lock` | `pytest api/tests/test_lock.py -q` |
| Security checks | - | `pip-audit --skip-editable`, `npm --prefix web audit --omit=dev`, `govulncheck ./...` in `upload-service`, `gitleaks git .` - all run weekly in `.github/workflows/security.yml` |

For the ML folders, use their own environment so the large PyTorch install
stays out of the main one: `python -m venv ml/frames/.venv`, then
`pip install torch --index-url https://download.pytorch.org/whl/cpu` and
`pip install -r ml/frames/requirements.txt -e workers` (and the same for
`ml/leds`). With an NVIDIA GPU, install the CUDA build of PyTorch instead to
benchmark it.

## What only the owner can prove

CI has no real game, no display, no phone, no ESP32 and none of the owner's
accounts. Each of these is untested until the owner does it. The bundled
PresentMon, the automatic fetch and the load check have so far only been
through the unit tests and the script analyzer (Pester and PSScriptAnalyzer
on Linux, and the Python tests); none of the three has run on Windows yet.

| What | Where | How to know it worked |
|---|---|---|
| A capture on a real gaming PC | Your PC, with the collector zip from a release or a server (PresentMon is inside) and LibreHardwareMonitor running | The run shows frame-time and temperature charts and no "could not be read" notes |
| The bundled PresentMon runs | Same, straight from the unpacked zip, with no internet | `collector.log` names `tools\PresentMon-2.6.0-x64.exe`; no warning about its signature; `presentmon.csv` has rows |
| The load check waits when no game is running | Your PC: start a capture on an idle desktop, then start a game | It says nothing seems to be running and waits; the capture begins by itself once the game is under load; the manifest's `capture.load_at_start` has `busy: true` and `waited_seconds` above 0. Also try Enter (captures anyway) and leaving it idle for 3 minutes (the run carries the idle warning) |
| A git copy fetches PresentMon by itself | A PC with internet and a git checkout (no `collector\tools` folder): start a capture | The collector says it is fetching PresentMon, `tools\PresentMon-2.6.0-x64.exe` appears, and the run has frame times. With `-NoDownload`, or offline, the capture runs without frame times and says so |
| LibreHardwareMonitor sensor names on real hardware | Same | `sensors.csv` has CPU and GPU temperature columns filled in |
| The Rust collector against the PowerShell one | Same PC, same game, same length | Both runs diagnose the same; record each collector's CPU time and memory in [results.md](results.md) |
| Live view from a real PC | Master and a second PC on your network | The Live page updates while the game runs |
| Diagnosis accuracy | Labeled cases in `eval/cases/` ([fault-testing.md](fault-testing.md)) | `python eval/run_eval.py --real-only`, with the case count |
| Photo reading on real phone photos | Your phone, real error screens | `python eval/photo_eval.py`, as "N of M" |
| The QR photo flow | Your phone on the same network | A photo arrives in **Photos** |
| The AI helper and troubleshooter | Your Anthropic key, with a spending cap | Answers cite only the run's findings |
| Discord and Google sign-in | Your Discord and Google developer apps | Sign in, then check **Account** shows the identity |
| The Discord bot | A server whose moderators approved it | `/diagnose` with a run zip replies with a summary |
| The start script's Docker route | Windows with Docker Desktop | `Start-PCDoctor.cmd` opens the dashboard |
| The first collector release | Push a `collector-v...` tag | The release has the zip and its hash, `gh attestation verify` passes, and the zip contains `tools/PresentMon-2.6.0-x64.exe` and `PresentMon-LICENSE.txt` |
| The Rust collector's Windows-counter fallback | Your PC with LibreHardwareMonitor closed | `sensors.csv` has CPU load, speed, RAM and GPU load; the manifest says `"source": "windows"` |
| Cloud hosting | An AWS account and a domain, HTTPS only | [deploy/README.md](../deploy/README.md) section 3 |
| k6 throughput | Your PC or the cloud server | Record requests per second and error rate at a stated load |
| The model and LED reader on real data | Real labeled cases and LED photos | The same scripts with real data; record counts, not just percentages |
| GPU inference speed | Your PC's GPU | `python ml/frames/benchmark.py`, naming the GPU and batch size |
| The sensor node | ESP32 and SHT31, USB powered, never wired to the PC's headers | The receiver's summary: sample rate and packet loss |
