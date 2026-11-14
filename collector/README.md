# Collector

A read-only PowerShell script that gathers a PC's hardware health and
performance data into one folder. Nothing is installed and nothing on the PC
is changed. It works from a USB stick, with no internet, on any Windows 10 or
11 PC (Windows PowerShell 5.1 or PowerShell 7).

## Use it

1. Copy this `collector` folder to the PC (or a USB stick).
2. Double-click **`PCDoctor.cmd`**. Windows asks for administrator rights -
   needed for disk health counters and frame times.
3. Choose:
   - **Quick health check** (about 20 seconds): specs, crash and hardware
     events from the last 30 days, disk health.
   - **Performance capture** (5 minutes): the same, plus frame times and
     sensor readings while a game or stress test runs.
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
the collector** page shows the hash. PresentMon is a separate download; the
collector runs it only if it carries Intel's signature.

## For a capture: two free tools

| For | Tool | Set-up |
|---|---|---|
| Frame times | Intel PresentMon | Run `Get-Tools.ps1` once on a PC with internet. It downloads one file into `tools\`, checks its SHA-256 and Intel's signature, and it then travels with the folder |
| Temperatures | LibreHardwareMonitor | Download it yourself, run it, and switch on **Options > Remote Web Server > Run**. Leave it running during the capture |

Without them a capture still records what Windows itself can report (CPU and
GPU load, CPU speed, RAM use, and an NVIDIA card's temperature and power) and
says clearly what is missing.

## From the command line

```powershell
.\Collect-PCDoctor.ps1 -Mode Quick
.\Collect-PCDoctor.ps1 -Mode Capture -Seconds 300 -Label "after repaste" -Process game.exe
.\Collect-PCDoctor.ps1 -Mode Quick -UploadUrl http://192.168.1.20:8080   # send it straight to the dashboard
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
