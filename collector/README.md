# Collector

A read-only PowerShell script that gathers a PC's hardware health and
performance data into one folder. It changes nothing on the PC, with one
exception: a capture can install a temperature driver, but only if you say
yes (or pass `-InstallTemperatureDriver`), and it removes it when the capture
ends (see "CPU temperature" below). It works from a USB stick, with no internet, on any Windows 10 or
11 PC (Windows PowerShell 5.1 or PowerShell 7).

## Use it

1. Copy this `collector` folder to the PC (or a USB stick). The zip from a
   release or from a PC Doctor server is this folder with PresentMon already
   inside.
2. Double-click **`PCDoctor.cmd`**. Windows asks for administrator rights -
   needed for disk health counters and frame times.
3. Choose:
   - **Quick health check** (about 20 seconds): specs, crash and hardware
     events from the last 30 days, disk health.
   - **Performance capture** (5 minutes): the same, plus frame times and
     sensor readings while a game or stress test runs. Start the game first.
     If nothing is running, the collector says so and waits (see below).
4. Drop the `PCDoctor-run-....zip` from the `runs` folder onto the dashboard.

Windows may warn about a downloaded script the first time ("Windows protected
your PC" > More info > Run anyway). The script is unsigned for now.

The console also prints the red flags straight away (blue-screen stop codes,
unexpected shutdowns, disk errors), so you get something even with no
dashboard to hand.

## Check your copy before running it

The collector asks for administrator rights, so make sure it is the real
one. Each collector release on GitHub (tags `collector-v...`) has an
attestation: a signed record that GitHub's release workflow built that exact
file from this repository.

```bash
gh attestation verify PCDoctor-collector.zip --repo HU3YN/PC-Doctor
```

Without `gh`, compare the file's hash with the one on the release page (open
the page over HTTPS yourself, not through a link from somewhere else):

```powershell
Get-FileHash .\PCDoctor-collector.zip -Algorithm SHA256
```

A PC Doctor server serves the same bytes for the same version, and its **Get
the collector** page shows the hash. (A server that does not have PresentMon
offers a zip without it, with a different hash; the page says so.)

The zip contains one program that is not ours: Intel's PresentMon, as
`tools\PresentMon-2.6.0-x64.exe`, unmodified, with Intel's licence (MIT) in
`PresentMon-LICENSE.txt`. The build puts it in only if its SHA-256 is the one
pinned in `Get-Tools.ps1`, and the collector runs it only if it carries
Intel's signature.

## For a capture: two tools

| For | Tool | Set-up |
|---|---|---|
| Frame times | Intel PresentMon | None: it is in the zip. A copy without it (a git checkout) fetches it at the first capture - see below |
| CPU temperature | LibreHardwareMonitor, or the temporary driver below | Either start LibreHardwareMonitor yourself (**Options > Remote Web Server > Run**, leave it running; the collector uses it first), or answer yes when the collector offers the temporary driver |

A graphics card's temperature needs nothing extra. An NVIDIA card's comes
from the signed `nvidia-smi` that the driver installs. On AMD and Intel
graphics (or when `nvidia-smi` gives nothing) the collector reads the GPU
temperature, and the fan speed where the driver reports one, from Windows' own
graphics-adapter counters - the source of Task Manager's GPU temperature
(Windows 10 1803 or later, `D3DKMTQueryAdapterInfo` in gdi32.dll). It follows
the busiest adapter; a driver that reports 0 there gives no reading. Such runs
keep `sensors.source` = `windows`, so the source of `gpu_temp_c` is not named
in the manifest. Not yet proven on a real AMD or Intel GPU.

### CPU temperature: the temporary driver

Windows does not give CPU temperature to ordinary programs. When
LibreHardwareMonitor is not running and the collector runs as administrator
in Capture mode, it can read it through a driver:

- If PawnIO is already installed on the PC, the collector uses it and leaves it
  alone.
- Otherwise it asks: "Install it for this capture? [y/N]". The default is no.
  Close games with anti-cheat first.
- `-InstallTemperatureDriver` installs without asking (for unattended runs).
  `-NoTemperatureDriver` never offers it.

What is used: PawnIO 2.2.0.0 by namazso (`tools\PawnIO_setup.exe`, GPL-2.0,
unmodified) and LibreHardwareMonitorLib 0.9.6 with 13 other libraries
(`tools\lhm`, MPL-2.0; licences in `licences\`). Every file is pinned by
SHA-256 in `temperature-tools.json` and checked again before use, and the
installer must also carry namazso's signature. If any check fails, none of
them is used. Sensors are read in a separate Windows PowerShell 5.1 process.

When the capture ends (also on Ctrl+C) the collector removes what it
installed: PawnIO's own uninstaller, then the leftover driver package and the
stopped service (`pnputil`, `sc delete`), and checks nothing is left. If the
window is closed mid-capture, a marker file
(`%ProgramData%\PCDoctor\pawnio-installed-by-pcdoctor.txt`) lets the next run
as administrator remove it. The manifest records what happened in
`capture.temperature_driver`.

Every capture also measures its own cost (CPU time and memory of the
collector, PresentMon and the temperature reader) and prints it at the end; it
is recorded in `capture.overhead`.

To remove it by hand: Settings > Apps > Installed apps > PawnIO > Uninstall.

Not yet proven on a real PC: a real CPU temperature reading, Memory Integrity
(HVCI) switched on, and games with anti-cheat. See
[docs/testing.md](../docs/testing.md#what-only-the-owner-can-prove) and
[docs/threat-model.md](../docs/threat-model.md).

Without them a capture still records what Windows itself can report (CPU and
GPU load, CPU speed, RAM use, the GPU temperature where Windows' adapter
counters have one, and an NVIDIA card's temperature and power) and
says clearly what is missing.

### When PresentMon is not in the folder

A copy from git has no `tools\PresentMon-...-x64.exe`. At the first capture
the collector runs `Get-Tools.ps1` itself: one download from github.com
(Intel's release), kept only if its SHA-256 is the pinned one and it carries
Intel's signature, given up after 60 seconds. The file stays in `tools\` and
travels with the folder. With no internet the capture goes ahead without
frame times and says so. `-NoDownload` switches the download off. You can
still run `Get-Tools.ps1` by hand beforehand, but you do not have to.

### What happens when a capture starts

After the countdown the collector takes three load readings. The PC counts as
under load when the graphics card is at 30% or more, or the CPU at 50% or
more (the middle reading of the three). If it is idle, the collector says so
and waits up to 3 minutes for a game or stress test to start; press Enter to
capture anyway. If the PC is still idle, the run carries a warning, because
the performance checks then have nothing to judge. With `-NonInteractive`
nothing waits. The readings are saved in `manifest.json` under
`capture.load_at_start`.

You do not pick the game. After the capture, the collector keeps the frames
of the busiest program on screen that is not part of the Windows shell
(`-Process game.exe` names it yourself).

## From the command line

```powershell
.\Collect-PCDoctor.ps1 -Mode Quick
.\Collect-PCDoctor.ps1 -Mode Capture -Seconds 300 -Label "after repaste" -Process game.exe
.\Collect-PCDoctor.ps1 -Mode Quick -UploadUrl http://192.168.1.20:8080   # send it straight to the dashboard
.\Collect-PCDoctor.ps1 -Mode Capture -NoDownload                         # never fetch PresentMon, even if it is missing
.\Collect-PCDoctor.ps1 -Mode Capture -InstallTemperatureDriver           # install the temperature driver without asking
.\Collect-PCDoctor.ps1 -Mode Capture -NoTemperatureDriver                # never offer it
Get-Help .\Collect-PCDoctor.ps1 -Full
```

## What it reads

Exactly what is listed in [docs/privacy.md](../docs/privacy.md) - and never a
computer name, user name, serial number or file name. Every output file is
plain text you can open in Notepad.

## Working on it

```powershell
Invoke-Pester collector/tests                                # unit tests
collector/tests/Invoke-IntegrationTest.ps1 -Mode Quick       # runs the real collector and checks the output
Invoke-ScriptAnalyzer -Path collector -Recurse -Settings collector/PSScriptAnalyzerSettings.psd1
```

Keep the scripts plain ASCII: Windows PowerShell 5.1 misreads UTF-8 without a
byte-order mark. CI checks this, and runs all of the above on real Windows.
