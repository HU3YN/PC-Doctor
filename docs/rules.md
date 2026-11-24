# The rules engine

Each rule is one small function that looks for one kind of fault and returns
findings written the way a technician would explain them. The code is in
`workers/pcdoctor_analysis/rules/`; `pcdoctor-analyze rules` prints this list.

A rule answers one of three ways, and the dashboard shows which:

- **found** - here is the problem, the numbers behind it, and what to check next
- **passed** - it looked and found nothing wrong
- **not checked** - the run does not contain the data it needs (it never guesses)

## What it detects

| Code | Kind | Detects | Needs |
|---|---|---|---|
| `hardware.whea_fatal` | Processor | The hardware reported an error it could not recover from. | the Windows event log |
| `hardware.whea_corrected` | Processor | The hardware keeps making errors that it manages to correct - an early warning. | the Windows event log |
| `power.unexpected_shutdown` | Power / PSU | The PC lost power or froze and was forced off, without a blue screen. | the Windows event log |
| `stability.bluescreen` | Windows / software | Windows crashed with a stop code (blue screen). | the Windows event log |
| `gpu.driver_timeout` | Graphics card | The graphics driver stopped responding and Windows restarted it. | the Windows event log |
| `storage.io_errors` | Storage (SSD / HDD) | Windows logged bad blocks, drive resets, I/O retries or file-system corruption. | the Windows event log |
| `memory.diagnostic_failed` | Memory (RAM) | Windows Memory Diagnostic found bad memory. | a Windows Memory Diagnostic result in the event log |
| `cpu.firmware_speed_limit` | Processor | The firmware is holding the processor below full speed. | the Windows event log |
| `performance.stutter` | Performance | Uneven frame times: spikes, hitches, or 1% lows far below the average. | a PresentMon capture |
| `performance.gpu_limited` | Performance | The graphics card is the limit on frame rate (normal in most games). | GPU load from sensors, or GPU busy time from PresentMon |
| `performance.cpu_limited` | Performance | The processor is the limit on frame rate while the graphics card waits. | GPU and CPU load from sensors |
| `storage.disk_unhealthy` | Storage (SSD / HDD) | Windows reports a disk as unhealthy, or the disk has uncorrectable errors. | disk health from the collector |
| `storage.ssd_worn` | Storage (SSD / HDD) | An SSD has used most of its rated write life. | disk reliability counters (needs administrator) |
| `storage.drive_hot` | Thermal / cooling | A drive runs hot enough to slow itself down or wear faster. | disk reliability counters (needs administrator) |
| `storage.low_space` | Storage (SSD / HDD) | A volume is almost full. | volume sizes from the collector |
| `memory.single_channel` | Memory (RAM) | Only one memory module is fitted, so the RAM runs in single-channel mode. | memory modules from the collector |
| `memory.slow_speed` | Memory (RAM) | The RAM runs slower than it is rated for - the XMP/EXPO profile is probably off. | memory module speeds from the collector |
| `memory.mixed_modules` | Memory (RAM) | The memory modules are different sizes or different models. | memory modules from the collector |
| `memory.ram_exhausted` | Memory (RAM) | The PC ran out of free memory during the run. | RAM usage from sensors |
| `gpu.vram_exhausted` | Graphics card | The graphics card ran out of video memory during the run. | VRAM usage from sensors |
| `driver.gpu_missing` | Driver | No real graphics driver is installed (Microsoft Basic Display Adapter). | graphics adapters from the collector |
| `driver.gpu_old` | Driver | The graphics driver is old. | graphics driver dates from the collector |
| `os.power_saver_plan` | Windows / software | Windows is set to the Power saver plan, which caps CPU speed. | the active power plan from the collector |
| `display.refresh_below_max` | Peripheral / display | A screen runs at a much lower refresh rate than it can do. | the screens and their refresh rates from the collector |
| `power.battery_worn` | Power / PSU | The laptop battery has lost a large part of its capacity. | battery capacities from the collector |
| `thermal.cpu_hot` | Thermal / cooling | The processor runs too hot under load. | CPU temperature from sensors |
| `thermal.cpu_throttling` | Thermal / cooling | The processor slows itself down when it gets hot. | CPU temperature and CPU clock speed from sensors |
| `thermal.gpu_hot` | Thermal / cooling | The graphics card runs too hot under load. | GPU temperature from sensors |
| `thermal.gpu_throttling` | Thermal / cooling | The graphics card cuts its clock speed when it gets hot. | GPU temperature, clock speed and load from sensors |
| `thermal.shutdown` | Thermal / cooling | Windows shut the PC down because a temperature sensor hit its critical limit. | the Windows event log |

## Severity

- **Critical** - hardware is failing, data is at risk, or the PC is unstable.
- **Warning** - a real problem that hurts performance or reliability.
- **Info** - worth knowing; often explains the numbers rather than a fault
  (a GPU-limited game is normal).

Within a severity, causes are listed before symptoms: an overheating CPU is
the headline, the stutter it causes comes after it.

## Thresholds

Every number is in one place: `Thresholds` in `workers/pcdoctor_analysis/model.py`.
They are **starting values** from common technician practice and component
limits - not measured optimums. Phase 2 tunes them against real labeled
captures, recording the score before and after each change.

| Threshold | Value | Reasoning |
|---|---|---|
| Frame spike | more than 2x the median of the previous 30 frames, and at least 8 ms longer | Relative to recent frames, so a slow scene is not a "spike"; the 8 ms floor ignores wobble nobody can feel at high FPS |
| Hitch | a spike of 100 ms or more | Clearly felt as a freeze |
| Stutter warning | 4+ spikes a minute, or 1% low under 45% of the average | |
| GPU-limited | median GPU load 95%+ | |
| CPU-limited | median GPU load under 85% while the busiest core is 85%+ | The GPU is waiting |
| CPU hot | peak 90 °C+, or 85 °C+ for a quarter of the run; critical at 100 °C | Many CPUs throttle at 95-100 °C. Recent Ryzen and high-end Core chips run into the 90s by design, so this is read together with the throttling rule |
| CPU throttling | clock 15%+ lower at 90 °C+ than below 85 °C, both under load | Compares the run with itself; idle clock drops are ignored |
| GPU hot | core 87 °C+ (critical 95 °C+), hot spot 100 °C+ (critical 110 °C+) | |
| Drive hot | SSD 70 °C+, hard drive 55 °C+ | NVMe drives throttle when hot |
| SSD worn | 80%+ of rated life used (critical 95%+) | |
| Low space | under 10% free, or under 15 GB on the Windows drive | |
| RAM / VRAM full | 95% / 97%+ for the worst 5% of the run | A single momentary peak does not count |
| Unexpected shutdowns | any is a warning; 3+ in 30 days is critical | |
| Slow refresh rate | a higher rate is offered that is 1.2x+ and 20 Hz+ above the current one | So 59 vs 60 Hz (the same mode) never fires. If Windows offers no higher rate but the screen's own list does, the finding points at the cable or port |
| Old graphics driver | 18+ months (info only) | Windows' own built-in drivers are skipped: they are all dated 2006-06-21 |

## Adding a rule

1. Write a function in the right file under `rules/`, decorated with `@rule(...)`.
   Return `None` for "no data", `[]` for "fine", or a list of `Finding`s.
2. Write the summary for a person: what was seen, what it means, in plain
   words. Put the numbers in `evidence` and the steps in `next_checks`.
3. Add tests in `workers/tests/test_rules.py`: it fires on the fault, stays
   quiet just under the line, and returns `None` without its data.
4. Bump `RULES_VERSION` in `pcdoctor_analysis/__init__.py`. Stored runs then
   show "analysed with older rules" and can be re-analysed in one click.
