# Roadmap: phases, and the skills each one teaches

The point of this project is twofold: a tool worth using at work, and practice
in the skills internship postings ask for. This page maps one to the other.

## Where things stand

**Phase 1 is built**, with one item left that only you can do: test it on your
own gaming PC (see [results.md](results.md), "Not verified yet").

| Phase 1 item | Status |
|---|---|
| PowerShell collector: specs, events, disk health, memory test results, PresentMon and sensors in one folder | Done - `collector/` |
| Python rules engine | Done - 29 fault types, `workers/` |
| FastAPI backend with PostgreSQL | Done - `api/` |
| React + TypeScript dashboard: frame-time chart, temperature chart, findings | Done - `web/` |
| Docker Compose and a GitHub Actions workflow that runs the tests | Done |
| Work log with search and similar-case matching (added) | Done |
| Test on my own PC | **To do** |

## Skills from the plan's gap list

| Skill | Where it is in this repo now | What to build next to deepen it |
|---|---|---|
| React, TypeScript | `web/` - typed API client, React Query, routing, charts | Build comparison view (Phase 5); component tests |
| PostgreSQL | `api/` - schema, foreign keys with cascade, JSONB, Alembic migrations, tests on a real PostgreSQL in CI | Full-text search with `tsvector` for the work log; query plans with `EXPLAIN` |
| Docker | `api/Dockerfile`, `web/Dockerfile`, `docker-compose.yml` | Multi-stage build tuning, image scanning |
| CI | `.github/workflows/ci.yml` - Linux, Windows, PostgreSQL service, Compose smoke test | Release workflow that publishes images |
| Security | Read-only collector, privacy tests, defensive upload unpacking, download checked by hash and signature | Logins and per-user access (Phase 4); signed collector builds |
| Machine learning, PyTorch | Not started. `eval/run_eval.py` is ready to score a model against the rules | Phase 3: train a stutter detector on frame-time series; `ml/` |
| Computer vision | Not started. Stop-code table is ready for lookups | Phase 5: read stop codes from blue-screen photos |
| Go | Not started | Phase 4: `upload-service/` |
| Message queues, Redis | Not started. Analysis is one function call (`ingest()`), easy to move behind a queue | Phase 4 |
| Kubernetes, AWS | Not started | Phase 4: k3s on one small server; `deploy/` |
| Monitoring | Not started | Phase 4: Prometheus metrics on the API, Grafana dashboard |

A note on learning: Phase 1 was built quickly so there is something real to
use. The skills in the bottom half of the table are worth building by hand,
slowly - that is where the learning is. Read the Phase 1 code first; each
folder's README says how it fits together.

## Phase 2 - AI troubleshooter and evaluation

- Build the labeled fault set: [fault-testing.md](fault-testing.md). Aim for
  20+ real cases before trusting any accuracy number.
- `python eval/run_eval.py --real-only` scores the rules; record it in
  results.md before and after every change.
- Add an agent that turns findings and logs into a diagnosis. Findings are
  already structured (code, evidence, next checks), which is what an agent
  needs as input. Keep the API key in `.env`, set a monthly spending cap.

## Phase 3 - Machine learning model

- Train on frame-time and sensor series (`ml/`). Compare with the rules engine
  on the same labeled set and report both.
- Measure inference speed on CPU and GPU, naming the machine.

## Phase 4 - Cloud and scale

- Go upload service, a job queue, Redis cache.
- k3s on one small AWS server (not EKS). Prometheus and Grafana.
- Logins and per-user access. Until this exists, do not expose the app to the
  internet.

## Phase 5 - Photo reader and build comparison

- Read a stop code or POST code from a photo; look it up in the stop-code table.
- Compare a run with runs from similar parts.
- Screenshots and a short demo video for the README.

## Side projects for the gaps this project does not cover

- **Chip roles:** SystemVerilog and UVM testbench for the 4-bit carry-lookahead adder.
- **Embedded roles:** Arduino reading a sensor over I2C, logging over UART.
