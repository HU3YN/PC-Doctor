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

## The everyday workflow

One computer is the **master** - your laptop or bench PC. It holds the
dashboard, every diagnosis and your work log. Everything else comes to it.

| The PC you are checking... | What you do |
|---|---|
| **Starts Windows** | Run the collector on it from a USB stick. The result is saved on the stick. Back at the master, drop the zip on the **Runs** page. |
| **Starts Windows and is on the same network** | Open the master's address in its browser, download the collector from **Get collector**, run it, and it uploads the result itself. No stick needed. |
| **Shows an error but will not load Windows** | Photograph the screen. On **Won't start**, upload the photo: the stop code is read off it and looked up, with any earlier job that had it. |
| **Shows nothing at all** | On **Won't start**, pick what you see (dead, debug LED on DRAM, beeps, ...) and follow the checklist. |

Every route ends the same way: **Log this job**, so the next similar one is quicker.

## Run it

### On the master computer: double-click

Get the code once ([Git](https://git-scm.com/download/win) needed):

```bash
git clone https://github.com/HU3YN/PC-Doctor.git
```

Then double-click **`Start-PCDoctor.cmd`** in that folder. It uses Docker if
Docker Desktop is running and Python if it is not, sets everything up the
first time (a few minutes), and opens the dashboard.

- **With Docker Desktop** running: nothing else to install. Includes photo reading.
- **Without Docker**: install [Python 3.11+](https://www.python.org/downloads/)
  (tick "Add python.exe to PATH") and, for the first start only,
  [Node.js 20+](https://nodejs.org/). Photo reading also needs the
  [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) program.

Click "Load demo data" to look around with made-up runs and notes (removed
again with one click).

### Letting other PCs reach the master

By default only the master itself can open the dashboard, because **there are
no logins yet**. On a network you trust (home, the shop bench), start it for
the network instead:

```bash
Start-PCDoctor.cmd -Lan
```

It prints the address other PCs should open, for example
`http://192.168.1.20:8080`. Allow it through Windows Firewall when asked. Do
not do this on public Wi-Fi, and do not put it on the internet until logins
exist (Phase 4). A USB stick always works and needs none of this.

### By hand

```bash
docker compose up -d --build
```

```bash
docker compose down
```

Data stays in Docker volumes between restarts (`docker compose down -v`
deletes it - use **Work log > Backup** first). Without Docker, see
[`api/README.md`](api/README.md) and [`web/README.md`](web/README.md).

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
| `upload-service/`, `bot/`, `ml/`, `sensor-node/`, `fuzz/`, `deploy/` | Placeholders for later phases |

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

Ten phases: AI troubleshooter and a labeled fault set, cloud and scale (Go,
Terraform, k3s, Prometheus), accounts and a Discord bot, a PyTorch model, a
Rust collector with streaming and DuckDB, an ESP32 sensor node, an inference
benchmark, security hardening, and a trained photo reader. See
[docs/roadmap.md](docs/roadmap.md).

## License

[MIT](LICENSE)
