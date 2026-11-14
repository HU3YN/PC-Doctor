# PC Doctor

Finds what is wrong with a Windows PC and explains it the way a technician
would: what was seen, what it means, and what to check next. It also keeps a
work log of the repairs you do, and shows you the earlier jobs that match the
problem in front of you.

> Working name. "PC-Doctor" is also the name of an existing commercial
> diagnostics product, so pick another before publishing this widely.

**Status:** all ten phases of the [roadmap](docs/roadmap.md) have working,
tested code, but most of it has only run in CI and a cloud build container.
Nothing has been tried on a real gaming PC, phone, Discord server or AWS
account yet - [what is verified](docs/results.md) and
[what only you can test](docs/testing.md#what-only-the-owner-can-prove).

## How it works

```
 the PC being checked                    your computer (or a server)
+----------------------+   .zip    +---------------------------------------+
|  collector           | --------> |  dashboard (React + TypeScript)       |
|  read-only PowerShell|  USB or   |     |                                 |
|  (or the Rust        |  upload   |  API (FastAPI) -> rules engine        |
|  capture collector)  |           |     |              (29 fault types)   |
|  specs, events,      |  live     |  PostgreSQL: runs, findings, work log |
|  disks, frame times, | --------> |  optional: Go upload service, Redis   |
|  sensors             |  NDJSON   |  queue + worker, Prometheus, Grafana  |
+----------------------+           +---------------------------------------+
   phone photos by QR code ------>   photo inbox (OCR)
   Discord /diagnose --------------> bot -> API as a guest
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

There are three kinds of visitor.

- **The master** (you, signed in) sees everything: every run, the work log,
  the photo inbox, live sessions. One account, created the first time the
  app starts.
- **A member** (optional: someone who signed in with Discord or Google) sees
  only the runs they uploaded while signed in. Off unless you set it up
  ([docs/oauth.md](docs/oauth.md)).
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

[`deploy/`](deploy/) has Terraform for one small AWS server running k3s, the
Kubernetes manifests, Prometheus alerts, a Grafana dashboard and a k6 load
test. They are checked for format and schema in CI but **have never been
applied to a real account**. Before exposing it to the internet: HTTPS only
(the sign-in cookie and photos must not travel in the clear), strong
passwords for PostgreSQL, Grafana and the metrics token, the master account
created straight away, and backups. [deploy/README.md](deploy/README.md) walks
through it.

### Watching a capture live

On the master, **Live** starts a session and shows an address. Give it to the
Rust capture collector (`--live-url`) and the page draws frame times and
temperatures while the game runs. The finished run is uploaded as usual.

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
them needs real, labeled faults ([fault-testing.md](docs/fault-testing.md)).

## Privacy

The collector reads hardware and performance data only. It never reads a
computer name, user name, serial number, file name or list of installed
programs - and CI fails if any of those shows up in real collector output.
Details: [docs/privacy.md](docs/privacy.md).

## Layout

| Folder | What is in it |
|---|---|
| [`collector/`](collector/) | Windows collector (PowerShell 5.1 and 7), launcher, tests |
| [`collector-rs/`](collector-rs/) | Rust capture collector (frames and sensors only), with live streaming |
| [`workers/`](workers/) | Python analysis: parsers, rules engine, stop-code guide |
| [`api/`](api/) | FastAPI backend: runs, findings, work log, sign-in, live sessions, build comparison, PostgreSQL migrations |
| [`web/`](web/) | React + TypeScript dashboard |
| [`upload-service/`](upload-service/) | Go upload service: checks uploads and queues them in Redis |
| [`bot/`](bot/) | Discord bot with `/diagnose` |
| [`deploy/`](deploy/) | Terraform, k3s manifests, Prometheus, Grafana, k6 load test |
| [`ml/frames/`](ml/frames/) | PyTorch frame-time model, ONNX export and benchmark |
| [`ml/leds/`](ml/leds/) | Debug-LED photo classifier (not wired into the API yet) |
| [`sensor-node/`](sensor-node/) | ESP32 + SHT31 case sensor: firmware and UDP receiver |
| [`eval/`](eval/) | Scoring for the diagnosis, the AI troubleshooter and the photo reader |
| [`fuzz/`](fuzz/) | Hypothesis fuzz tests for everything that reads files from strangers |
| [`docs/`](docs/) | Privacy, threat model, testing, run format, rules, roadmap, results |

## Develop

```bash
pip install -e "workers[dev]" -e "api[dev]"
```

```bash
pytest workers -q && pytest api -q
```

```bash
npm --prefix web test && npm --prefix web run lint
```

Every part has its own run and test command in
[docs/testing.md](docs/testing.md). Every push runs them in GitHub Actions -
on Linux, on PostgreSQL, on real Windows for the collectors - plus a security
workflow (dependency audits, secret scan, fuzzing) that also runs weekly. See
[`.github/workflows/`](.github/workflows/).

## Where it is going

The code for all ten phases exists; what is left is mostly real-world
testing and measuring: a capture on a real gaming PC, a labeled set of real
faults, real photos, real accounts and a real server. See
[docs/roadmap.md](docs/roadmap.md) and [docs/testing.md](docs/testing.md).

## License

[MIT](LICENSE)
