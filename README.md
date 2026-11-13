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

## Who sees what

There are two kinds of visitor.

- **The master** (you, signed in) sees everything: every run, the work log,
  the photo inbox. One account, created the first time the app starts.
- **A guest** (anyone, no account) can check one PC: download the collector,
  run it, and get a **private link** to that one diagnosis. A guest cannot
  list, search or open anything else - not other runs, not the work log.
  Their run also appears in the master's list, so the master can log the job.

## The everyday workflow

| The PC you are checking... | What happens |
|---|---|
| **Starts Windows and has a network** | Open the PC Doctor address in its browser, download the collector, run it. It uploads the result and opens the private diagnosis link. No sign-in. |
| **Starts Windows, no network** | Run the collector from a USB stick. The result is saved on the stick; drop the zip on the **Runs** page later. |
| **Will not start** | On the master, open **Photos** and show the QR code. Scan it with a phone and snap the error screen, the motherboard LEDs or the damaged part. The photo lands in the master's inbox within seconds, with any stop code already read and matched to earlier jobs. No app or sign-in on the phone. |
| **Shows nothing at all** | **Won't start** has a checklist for each symptom (dead, debug LED on DRAM, beeps, ...). |

Every route ends the same way for the master: **Log this job**. The work log
is the memory: next time the same stop code, part or symptom turns up, the
earlier job and its fix are shown first.

### The AI helper (optional)

With an Anthropic API key set (`ANTHROPIC_API_KEY` in `.env`), two buttons
appear for the master: **Describe with AI** on a photo (reads debug LEDs,
code displays and visible damage that plain OCR cannot) and **Draft the rest
with AI** on the job form. It runs only when pressed, fills only empty fields,
is told never to invent a cause or fix, and its output is a draft to check.
What you ask it about is sent to Anthropic. Without a key, everything else
works unchanged.

## Run it

### On the master computer: double-click

Get the code once ([Git](https://git-scm.com/download/win) needed):

```bash
git clone https://github.com/HU3YN/PC-Doctor.git
```

Then double-click **`Start-PCDoctor.cmd`** in that folder. The first time,
the window shows a **setup code**: type it into the browser to create your
master account (it proves you are at the master computer).

Double-click **`Start-PCDoctor.cmd`** again any time to start it. It uses Docker if
Docker Desktop is running and Python if it is not, sets everything up the
first time (a few minutes), and opens the dashboard.

- **With Docker Desktop** running: nothing else to install. Includes photo reading.
- **Without Docker**: install [Python 3.11+](https://www.python.org/downloads/)
  (tick "Add python.exe to PATH") and, for the first start only,
  [Node.js 20+](https://nodejs.org/). Photo reading also needs the
  [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) program.

Click "Load demo data" to look around with made-up runs and notes (removed
again with one click).

### Letting other PCs and phones reach the master

By default only the master computer itself can open the app. To let other PCs
download the collector and phones send photos, on a network you trust:

```bash
Start-PCDoctor.cmd -Lan
```

It prints the address to open, for example `http://192.168.1.20:8080`. Allow
it through Windows Firewall when asked. Guests on that network can check a PC
and send photos; only you can sign in and see what is stored.

### Putting it in the cloud

The sign-in is what makes hosting it reasonable: run the same Docker Compose
stack on a server, put HTTPS in front of it, and the collector and phones can
reach it from anywhere. That is Phase 3 of the roadmap and is **not done
yet**. Before exposing it to the internet: use HTTPS (the sign-in cookie and
photos must not travel in the clear), set a strong `POSTGRES_PASSWORD`, create
the master account straight away, and keep backups.

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
