# Privacy: what the collector reads, what it never reads, what it uploads

PC Doctor is about hardware and performance. It has no interest in who uses a
PC or what they do on it. This page is the full list. The collector is open
source and short, so you can check every line of it:
[`collector/PCDoctorCollector.psm1`](../collector/PCDoctorCollector.psm1).

## The collector is read-only

It changes no settings, installs no drivers and no software, and runs no
fixes. It reads, and writes its findings to one folder.

The collector download carries one program that is not ours: Intel's
PresentMon, unmodified, in its `tools` folder. It is run from there during a
capture and is not installed.

## What it reads

| What | Where from | Why |
|---|---|---|
| CPU, graphics card, motherboard and BIOS model and version | Windows (CIM) | To describe the build and compare it with others |
| Memory modules: size, speed, part number, slot and bank (channel) label | Windows (CIM) | Single-channel RAM, XMP off, mixed kits |
| Graphics driver version and date; screen resolution and refresh rate | Windows (CIM) | Old or missing drivers |
| Windows edition, version, build, last boot time | Windows (CIM) | Context for crashes |
| Active power plan | `powercfg /getactivescheme` | Power saver slows a PC down |
| Battery design and current capacity (laptops) | Windows (WMI) | Worn batteries |
| Disk model, type, firmware, Windows disk number, health, wear, temperature, error counts | `Get-PhysicalDisk`, `Get-StorageReliabilityCounter` | Failing or worn drives |
| Size and free space of each drive letter | `Get-Volume` | Full drives |
| Hardware events from the last 30 days: hardware errors (WHEA), unexpected shutdowns, blue-screen stop codes, thermal shutdowns, memory test results, disk errors, graphics driver resets, firmware speed limits | Windows System event log | Crashes and failing parts |
| Frame times of **one** program during a capture | PresentMon | Stutter and frame rate |
| Temperatures, loads, clock speeds, power, fan speed, memory use during a capture | LibreHardwareMonitor, or Windows itself and `nvidia-smi` | Overheating, throttling, bottlenecks |

The exact list of event providers and ids is in `$script:EventQueries`, and the
only event data fields kept are in `$script:EventDataKept`, both at the top of
the module.

## What it never reads

- **No names.** Not the computer name, not user names, not the Windows owner.
- **No serial numbers.** Not of the PC, the board, the disks or the memory.
- **No network identity.** No IP or MAC addresses, no Wi-Fi names.
- **No files.** No file names, folders, documents, or browser data.
- **No list of what is running or installed.** PresentMon sees every program
  that draws to the screen; the collector keeps the rows of the one program
  being tested and deletes the rest before the run is saved. Only a count of
  how many others were removed is kept.
- **No volume labels** (people name drives after themselves).

As a second line of defence, any text taken from Windows (event messages) is
scrubbed before it is saved: user-folder paths, serial numbers, the computer
name and the current user name are replaced with placeholders.

This is tested, not just promised: on every change, CI runs the collector on a
real Windows machine and fails if the computer name, the user name or a serial
number appears anywhere in the output (`collector/tests/Invoke-IntegrationTest.ps1`).

## What goes over the network

The collector download from a release or a PC Doctor server fetches nothing
from the internet. (It talks to the network only to upload a run to your
PC Doctor server, when you give it one.)

There is one case where the checked PC makes a request by itself. A copy of
the collector without PresentMon (a git checkout) fetches it at the first
capture: one download from github.com, kept only if it is the exact file
expected (pinned SHA-256) and Intel signed it. The request sends nothing
about the PC. GitHub sees the PC's IP address, as it does for any download.
`-NoDownload` switches this off; the capture then has no frame times.

The master computer makes the same one download when `Start-PCDoctor.cmd`
starts it without Docker (or when its Docker image is built), so that the
collector it offers has PresentMon inside.

## What is uploaded

Nothing, unless you upload it. The collector writes a folder and a zip next to
itself. You upload the zip by dropping it on the dashboard, or by giving the
collector `-UploadUrl`. The server keeps only the known files from the zip
(`manifest.json`, `specs.json`, `events.json`, `disks.json`, `presentmon.csv`,
`sensors.csv`, `sensors_raw.json`, `collector.log`) and ignores anything else.

Open any of them in Notepad - they are plain text. The format is described in
[run-format.md](run-format.md).

## Who can see what

Everything stored - runs, findings, the work log, photos - is visible only to
the signed-in master. Someone without an account can upload a run and open
that one run through a private link; the link's key is random, and only a
hash of it is stored. They cannot list or open anything else. A test fails
the build if any part of the API is left open by accident
(`api/tests/test_auth.py`).

The master's password is stored as a salted scrypt hash. Sign-in sessions are
random tokens kept in an HttpOnly cookie; the database holds only their hashes.

## Signing in with Discord or Google

This is optional and off until the master sets it up ([oauth.md](oauth.md)).

- **What is asked for.** The smallest scope each provider has: `identify` on
  Discord, `openid` on Google. No email, no friends list, no servers.
- **What is stored.** The provider's name and its id for the person (Discord's
  user id, Google's `sub`) - nothing else: no name, email or picture
  (`Identity` in `api/pcdoctor_api/models.py`). The account gets a made-up
  username such as `discord-1a2b3c4d` and no password. The provider's access
  token is used once to read the id and is not kept.
- **What a member can see.** Only the runs they uploaded while signed in, and
  of those only the diagnosis: not the master's notes, not the work log, not
  similar cases from other people's runs (`/api/me` in
  `api/pcdoctor_api/routers/runs.py`). They can delete their own runs. Every
  master-only route answers 403 to a member, and a test checks each one
  (`api/tests/test_auth.py`).
- **Who can sign in.** With `PCDOCTOR_OAUTH_SIGNUP=false` (the default), only
  identities the master has linked. With `true`, anyone with a Discord or
  Google account gets a member account. The master can remove members; their
  identities go with them.

## Notifications and the Discord bot

- **The webhook** (`PCDOCTOR_NOTIFY_WEBHOOK_URL`, optional) is sent one line
  when a guest uploads a run: the verdict and the headline, e.g. "New guest
  run (warning): GPU runs hot". Never the private link, the label, the PC's
  parts list or anything about who sent it (`api/pcdoctor_api/services/notify.py`).
- **The bot** (`bot/`) uploads a file someone gives it to `/diagnose` as a
  guest, under a fixed file name (the person's own file name is not sent),
  and replies with the summary. The reply is visible only to that person
  unless they choose to show the summary to the channel; the private link
  always goes to them alone. The bot keeps nothing. Its token (`PCDOCTOR_BOT_TOKEN`) only gives it a higher
  upload limit; it cannot read any run.

## Live view

Optional. When the master starts a live session and the capture collector is
given its address (`--live-url`), the collector sends frame times and sensor
readings while it runs - the same numbers that end up in `presentmon.csv`
and `sensors.csv`, without program names. They are held in memory (or in
Redis) for at most 6 hours, never written to the database, and visible only
to the master. The session's address can only add samples; it reads nothing.

## Photos

Photos sent through a QR link are **stored** on the master (they are the
record of a PC that could not run the collector). Before storing, each photo
is re-encoded, which removes the location, phone model and other hidden data
cameras put in the file. Only the master can view or delete them. The link a
phone uses can add photos for 12 hours and can read nothing.

A photo uploaded directly on the "Won't start" page is read in memory and not
stored. Either way: photograph the PC, not people or paperwork.

If the optional AI helper is switched on and you press its button, that photo
or text is sent to Anthropic's API. It is never sent automatically.

## The work log

The work log is your own notes about repairs. The rule is the same: the
machine and the fix, never the customer. The form says so, and an entry that
looks like it contains an email address, a phone number, a serial number or a
customer's name is flagged with a warning. Your own job number is fine.

## For shop machines (KT Electronics)

- Ask the owner before running the collector on a shop or customer machine.
- Never put customer names, serial numbers or customer data in this
  repository, in sample data, or in the work log.
- The label you type for a run is yours to choose: "bench 3, GPU swap", never
  a customer's name.
