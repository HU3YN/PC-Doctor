# Roadmap: ten phases, and the skills each one teaches

Two goals: a tool worth using at work, and real practice in the skills
internship postings ask for. The plan's own rules apply: **ship in order**,
and **only finished, measured work goes on a resume**.

## Where things stand (2026-11-14)

"Built" means the code exists and its tests pass in CI. It does not mean it
has been tried on real hardware or real accounts - the right-hand column says
what is still missing. [testing.md](testing.md) lists what only the owner
can check.

| Phase | What | Status | Still missing |
|---|---|---|---|
| 1 | Collector, 29-rule diagnosis, API, dashboard, work log, start script | Built | A capture on a real gaming PC |
| 2 | AI troubleshooter (`POST /api/assist/troubleshoot`) and its scoring script (`eval/agent_eval.py`) | Built | A run against the real API; real labeled cases |
| 3 | Go upload service, Redis queue and worker, Prometheus metrics, Grafana, alerts, k6 load test, Terraform and k3s files | Built | Terraform and k3s applied to a real AWS account; k6 numbers |
| 4 | Discord and Google sign-in (OAuth with PKCE), member accounts, webhook, Discord bot, bot upload token | Built | Real Discord/Google apps; the bot on a moderator-approved server |
| 5 | Frame-time model (PyTorch 1-D CNN) compared with the stutter rule | Built, synthetic data only | Real labeled cases in `eval/cases/` |
| 6 | Rust capture collector, live streaming, DuckDB build comparison | Built | A run on Windows with a real game; overhead measured against PowerShell |
| 7 | ESP32 + SHT31 case sensor: firmware, UDP receiver | Built, host tests only | Compiled for the ESP32 and run on the board; loss and sample rate measured |
| 8 | ONNX export and CPU/GPU benchmark | Built | Run on the owner's PC (with a GPU) |
| 9 | Fuzzing, threat model, `SECURITY.md`, Dependabot, security workflow, signed-tool checks, CSP, attested collector releases | Built; 10 fuzz-found bugs fixed; 14 threat-model items fixed and 2 in part | The first real release; the few open items in [threat-model.md](threat-model.md) (plain HTTP on the LAN, session revocation, pinned dependencies) |
| 10 | Photo reader (OCR), no-boot checklist, debug-LED model | OCR built; LED model built, synthetic data only | Real photos: read rate, and LED photos to train on |

## An honest note about the resume

Every phase so far was built quickly, with an AI assistant, so that there is
something real to use. That makes it a good base and a good codebase to learn from - it
does not by itself make React or PostgreSQL a skill you can defend in an
interview. Before a skill goes on the resume, be able to explain the code and
change it yourself. A practical way: for each folder, read its README, then
make one real change on your own (ideas in the right-hand column below).

That now includes the later phases (Go, Rust, PyTorch, firmware), which hold
most of the listed skills. Treat them as worked examples: read them, run
them, break them, and rebuild a piece of each by hand. Use an assistant to
review and explain, not to write the next change for you.

## Skills from the plan's gap list

All of this was written with an AI assistant. A skill goes on the resume only
once you can explain the code and change it yourself; the right-hand column is
one change to make on your own for each.

| Skill | Phase | In the repo now | A change to make yourself |
|---|---|---|---|
| PostgreSQL | 1 | Schema, foreign keys with cascade, JSONB, a partial unique index, Alembic migrations, tests on real PostgreSQL in CI | Add full-text search on the work log with `tsvector` |
| React, TypeScript | 1 | Typed API client, React Query, routing, charts, a polled Live page | Add a "compare two runs" view |
| Docker, CI | 1 | Dockerfiles, Compose, CI on Linux, Windows and PostgreSQL | Add a release workflow that publishes images |
| LLM integration | 2 | `services/ai.py`, the troubleshooter, `eval/agent_eval.py` | Run the evaluation against the real API and record the score |
| Go | 3 | `upload-service/`: streaming zip checks, Redis queue, metrics, fuzz target | Add a per-address upload size budget per hour |
| Caches and message brokers | 3 | Redis job queue (blocking pop), shared rate limits, live-session buffers | Add a dead-letter list for jobs that fail three times |
| Monitoring | 3 | Prometheus metrics in three services, Grafana dashboard, alert rules | Add an alert on upload-to-diagnosis time |
| Cloud (AWS), Terraform, Kubernetes | 3 | `deploy/terraform`, `deploy/k8s` (format and schema checked only) | Apply it to a free-tier account and write down what broke |
| Load testing | 3 | `deploy/loadtest/upload.js` (k6) | Run it on your PC and record throughput and error rate |
| OAuth | 4 | Authorization code flow with PKCE written out by hand in `services/oauth.py` | Add GitHub as a third provider |
| Integrations | 4 | Discord webhook, `bot/` with `/diagnose` | Add a `/stopcode` command that uses the Look up data |
| PyTorch, ML evaluation | 5 | `ml/frames`: dataset split by series, a small CNN, a model card, evaluation against the rule | Add a second model (e.g. a GRU) and compare all three on the same set |
| ONNX, inference on CPU vs GPU | 8 | `ml/frames/export_onnx.py`, `benchmark.py` | Run the benchmark on your GPU and explain the batch-size curve |
| Rust | 6 | `collector-rs/`: tailing a growing file, filtering, zip, HTTPS streaming | Add the Windows performance-counter fallback the PowerShell collector has |
| Streaming data | 6 | NDJSON batches, bounded buffers in memory or Redis | Switch the Live page from polling to server-sent events |
| DuckDB | 6 | `services/compare.py`: ranks and quartiles in an in-memory table | Compare two builds against each other |
| C, I2C, UDP, firmware | 7 | `sensor-node/firmware` (SHT31 driver, CRC, packet format), Python receiver | Flash it, measure loss, then add a second sensor |
| Computer vision | 10 | OCR with screen cropping; `ml/leds` CNN from scratch | Collect real LED photos and train on them |
| Security, fuzzing | 9 | Hypothesis and Go fuzzing, threat model, pip-audit, npm audit, govulncheck, gitleaks | Fix one open item from the threat model |

## What each phase needs next

- **Phase 1:** run a capture on your own PC with PresentMon and
  LibreHardwareMonitor. Fix whatever the real hardware shows. Record it in
  [results.md](results.md).
- **Phase 2:** 20+ real labeled cases ([fault-testing.md](fault-testing.md))
  before trusting any accuracy number. Score the troubleshooter with a
  spending cap on the API key.
- **Phase 3:** apply the Terraform on a free-tier account, with HTTPS, and
  run k6 against it.
- **Phase 4:** register the Discord and Google apps; ask a server's
  moderators before the bot joins.
- **Phase 5:** retrain on real cases and compare with the rule on the same set.
- **Phase 6:** measure the Rust collector's overhead against the PowerShell
  one on a named PC and game.
- **Phase 7:** low-voltage parts only. Measure packet loss and sample rate.
- **Phase 8:** name the machine and batch size with every latency figure.
- **Phase 9:** fuzz only this project's code, on your own machines.
- **Phase 10:** measure the photo reader on real photos before wiring the
  LED model into the API.

## Separate projects for the gaps this one does not cover

- **Project A:** SystemVerilog and UVM testbench for the 4-bit carry-lookahead adder.
- **Project B:** a small 5-stage RISC-V CPU in Verilog on the FPGA board.
