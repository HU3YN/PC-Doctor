# PC Doctor

Finds what is wrong with a Windows PC and explains it the way a technician
would: what was seen, what it means, and what to check next. It also keeps a
work log of the repairs you do, and shows you the earlier jobs that match the
problem in front of you.

> Working name. "PC-Doctor" is also the name of an existing commercial
> diagnostics product, so pick another before publishing this widely.

**Status:** Phase 1 is built and tested (see [what is verified](docs/results.md)).
It has not yet been tried on a real gaming PC - that is the next step.

## How it works

```
 the PC being checked                    your computer
+----------------------+   .zip    +-------------------------------------+
|  collector           | --------> |  dashboard (React + TypeScript)     |
|  read-only PowerShell|  USB or   |     |                               |
|  specs, events,      |  upload   |  API (FastAPI) -> rules engine      |
|  disks, frame times, |           |     |              (29 fault types) |
|  sensors             |           |  PostgreSQL: runs, findings,        |
+----------------------+           |              work log               |
                                   +-------------------------------------+
```

1. **Collect.** Copy the [`collector`](collector/) folder to the PC (a USB
   stick works) and double-click `PCDoctor.cmd`. A quick health check takes
   about 20 seconds; a performance capture runs for 5 minutes while a game or
   stress test is going. It writes one zip file. It changes nothing on the PC.
2. **Diagnose.** Drop the zip on the dashboard. You get a verdict, each
   problem in plain English with the numbers behind it and the next checks in
   order, frame-time and temperature charts, and a list of what was checked
   and what could not be.
3. **Log the job.** One click turns a run into a work-log entry. Add what you
   checked, the cause and the fix. Next time a run or a symptom matches -
   same stop code, same kind of fault, same parts, similar wording - the
   earlier job shows up with its fix, under "You have seen this before".

There is also a **Look up** page: type a stop code (`0x124`) or describe a
problem ("restarts under load") to get what it means, where to look first, and
your own earlier cases.

## Run it

### With Docker (recommended)

```bash
docker compose up -d --build
```

Then open <http://localhost:8080>. Click "Load demo data" to look around with
made-up runs and notes (removed again with one click).

```bash
docker compose logs -f api
```

```bash
docker compose down
```

Your data stays in Docker volumes between restarts. `docker compose down -v`
deletes it, so use **Work log > Backup** first.

### Without Docker

Needs Python 3.11+ and Node 20+. Uses a SQLite file in `./data`, so there is
nothing else to install.

```bash
python -m venv .venv
```

```bash
.venv/bin/pip install -e workers -e api
```

```bash
npm --prefix web ci && npm --prefix web run build
```

```bash
.venv/bin/python -m pcdoctor_api
```

On Windows use `.venv\Scripts\pip` and `.venv\Scripts\python`. Then open
<http://localhost:8000>.

### Using it from another PC

By default the app only answers on the computer it runs on, because **there
are no logins yet**. On a network you trust (home, the shop bench), set
`PCDOCTOR_BIND=0.0.0.0` in `.env`, restart, and other PCs can open
`http://<this-computer's-address>:8080` - and the collector can send runs
straight to it with `-UploadUrl`. Do not put it on the internet until logins
exist (Phase 4). Moving a zip on a USB stick always works and needs none of this.

## What it can find

29 fault types, each with its own check ([full list and thresholds](docs/rules.md)):

- **Performance:** stutter and hitches, GPU-limited and CPU-limited games
- **Heat:** hot CPU or GPU, thermal throttling, thermal shutdowns, hot drives
- **Stability:** blue screens (with the stop code explained), hardware errors
  (WHEA), unexpected shutdowns, graphics driver resets
- **Storage:** failing disks, worn SSDs, disk and file-system errors, full drives
- **Memory:** failed memory tests, single-channel RAM, XMP off, mixed kits,
  RAM or video memory running out
- **Set-up:** missing or old graphics driver, Power saver plan, worn laptop
  battery, firmware limiting the CPU

The thresholds are sensible starting values, not measured optimums. Tuning
them against real, labeled faults is Phase 2.

## Privacy

The collector reads hardware and performance data only. It never reads a
computer name, user name, serial number, file name or list of installed
programs - and CI fails if any of those shows up in real collector output.
Details: [docs/privacy.md](docs/privacy.md).

## Layout

| Folder | What is in it |
|---|---|
| [`collector/`](collector/) | Windows collector (PowerShell 5.1 and 7), launcher, tests |
| [`workers/`](workers/) | Python analysis: parsers, rules engine, stop-code guide |
| [`api/`](api/) | FastAPI backend: runs, findings, work log, PostgreSQL migrations |
| [`web/`](web/) | React + TypeScript dashboard |
| [`eval/`](eval/) | Labeled fault cases and the scoring harness |
| [`docs/`](docs/) | Privacy, run format, rules, verified facts, safe fault testing, roadmap, results |
| `upload-service/`, `ml/`, `deploy/` | Placeholders for Phases 3 and 4 |

## Develop

```bash
pip install -e "workers[dev]" -e "api[dev]"
```

```bash
pytest workers api
```

```bash
ruff check workers api
```

```bash
npm --prefix web test && npm --prefix web run lint
```

```bash
python eval/run_eval.py
```

Every push runs all of this in GitHub Actions, on Linux, on PostgreSQL, and -
for the collector - on a real Windows machine. See
[`.github/workflows/ci.yml`](.github/workflows/ci.yml).

## Where it is going

Phase 2 adds an AI troubleshooter and a labeled fault set; Phase 3 a PyTorch
model; Phase 4 a Go upload service, a queue, Kubernetes on AWS and logins;
Phase 5 reading error codes from photos. See [docs/roadmap.md](docs/roadmap.md).

## License

[MIT](LICENSE)
