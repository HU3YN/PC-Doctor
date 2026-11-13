# Roadmap: ten phases, and the skills each one teaches

Two goals: a tool worth using at work, and real practice in the skills
internship postings ask for. The plan's own rules apply: **ship in order**,
and **only finished, measured work goes on a resume**.

## Where things stand

| Phase | What | Status |
|---|---|---|
| 1 | Collector and basic diagnosis | **Built.** One item left that only you can do: test it on your own gaming PC |
| - | Work log with similar-case matching (added) | Built |
| - | Master-PC workflow: one-click start, collector download, USB route (added) | Built |
| 10 (part) | Photo reader: stop codes read from a photo with an off-the-shelf OCR engine, and a no-boot checklist | Built early because it is needed at the bench. The trained vision model and build comparison are still Phase 10 |
| 2 | AI troubleshooter and evaluation | Harness ready (`eval/run_eval.py`); needs real labeled cases |
| 3 | Cloud and scale | Not started |
| 4 | Accounts, OAuth, Discord bot, real users | Not started |
| 5 | Machine learning model | Not started |
| 6 | Rust collector, streaming, DuckDB | Not started |
| 7 | ESP32 case-sensor node | Not started |
| 8 | Model inference benchmark | Not started |
| 9 | Security hardening | Not started (some groundwork exists, below) |
| 10 | Photo reader and build comparison | Partly built, see above |

## An honest note about the resume

Phase 1 was built quickly, with an AI assistant, so that there is something
real to use. That makes it a good base and a good codebase to learn from - it
does not by itself make React or PostgreSQL a skill you can defend in an
interview. Before a skill goes on the resume, be able to explain the code and
change it yourself. A practical way: for each folder, read its README, then
make one real change on your own (ideas in the right-hand column below).

The later phases are where most of the listed skills live. They are worth
building by hand, slowly - that is where the learning is. Use an assistant to
review and explain, not to write them for you.

## Skills from the plan's gap list

| Skill | Phase | In the repo now | A change to make yourself |
|---|---|---|---|
| PostgreSQL | 1 | Schema, foreign keys with cascade, JSONB, Alembic migrations, tests on real PostgreSQL in CI | Add a column with a migration; add full-text search with `tsvector` |
| React, TypeScript | 1 | Typed API client, React Query, routing, charts, six pages | Add a "compare two runs" view |
| Docker, CI | 1 | Two Dockerfiles, Compose, CI on Linux, Windows and PostgreSQL | Add a release workflow that publishes images |
| Computer vision | 10 | OCR with Tesseract (a ready-made neural OCR engine), image clean-up, tolerant code matching | Collect real photos, measure the read rate, then train a small model for debug LEDs |
| Machine learning, PyTorch | 5 | Nothing yet. `eval/run_eval.py` can score a model against the rules | Phase 5 |
| AI inference on CPU vs GPU | 8 | Nothing yet | Phase 8: ONNX Runtime benchmark, naming machine and batch size |
| Cloud (AWS), Terraform, Kubernetes | 3 | Nothing yet | Phase 3: one small server, defined in Terraform, running k3s |
| Monitoring | 3 | Nothing yet | Phase 3: Prometheus metrics on the API, Grafana dashboard, alerts |
| Load testing | 3 | Nothing yet | Phase 3: k6 against the upload service |
| Go | 3 | Nothing yet. `api/.../services/ingest.py` is the behaviour to reproduce | Phase 3: `upload-service/` |
| Caches and message brokers | 3 | Nothing yet. Analysis is one function call, easy to move behind a queue | Phase 3 |
| OAuth, sign-in | 4 | Nothing yet. **Until this exists the app has no logins** | Phase 4: authorization code flow with Discord or Google |
| Integrations (Discord bot, webhooks) | 4 | Nothing yet | Phase 4: `bot/` |
| Real users | 4 | `GET /api/stats` counts runs by week | Phase 4 |
| Rust | 6 | Nothing yet. The PowerShell collector and its tests define the behaviour | Phase 6 |
| Streaming data, DuckDB | 6 | Nothing yet | Phase 6 |
| I2C, UART, UDP, firmware | 7 | Nothing yet | Phase 7: `sensor-node/` |
| Security | 9 | Read-only collector, privacy tests in CI, defensive zip unpacking, photo size limits, download verified by hash and signature | Phase 9: `docs/threat-model.md`, fuzzing in `fuzz/`, dependency scanning, signed builds |

## What each remaining phase needs first

- **Phase 1, finish:** run a capture on your own PC with PresentMon and
  LibreHardwareMonitor. Fix whatever the real hardware shows. Record it in
  [results.md](results.md).
- **Phase 2:** 20+ real labeled cases ([fault-testing.md](fault-testing.md))
  before trusting any accuracy number. Then the agent: findings are already
  structured (code, evidence, next checks). Keep the API key in `.env` with a
  monthly cap.
- **Phase 3:** the Go upload service must keep the same limits as
  `ingest.py` (size caps, known file names only). Use k3s, not EKS.
- **Phase 4:** logins come before any public address. Bot only with
  moderators' approval.
- **Phase 5:** compare the model with the rules engine on the *same* labeled
  set and report both.
- **Phase 6:** measure the Rust collector's overhead against the PowerShell
  one on a named PC and game.
- **Phase 7:** low-voltage parts only. Measure packet loss and sample rate.
- **Phase 8:** name the machine and batch size with every latency figure.
- **Phase 9:** fuzz only this project's code, on your own machines.
- **Phase 10:** measure the photo reader on real photos; add build comparison.

## Separate projects for the gaps this one does not cover

- **Project A:** SystemVerilog and UVM testbench for the 4-bit carry-lookahead adder.
- **Project B:** a small 5-stage RISC-V CPU in Verilog on the FPGA board.
