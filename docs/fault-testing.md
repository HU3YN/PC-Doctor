# Making labeled fault cases safely

Phase 2 needs real captures where the cause is known, so the diagnosis can be
scored. The rule: **only create faults that cannot damage hardware.** If you
are not sure a test is safe, do not run it.

## Never

- No overvolting, no raising voltage or power limits above stock.
- No blocking airflow, unplugging fans, or removing a cooler.
- No letting a part sit at its thermal limit: stop a test when the CPU passes
  95 °C or the GPU passes 90 °C. Throttling protects the chip, but there is no
  reason to lean on it.
- No pulling power or forcing the PC off to "create" a crash.
- No testing on a machine with data that is not backed up.
- No customer machines without the owner's OK, and never customer data.

## Safe ways to create each kind of fault

| Fault to imitate | Safe method | Expect the tool to report |
|---|---|---|
| Weak cooling / throttling | Set a *lower* CPU power limit or temperature limit in the BIOS, or cap the fan curve at a moderate speed, then run a load. Watch temperatures and stop at 95 °C | `thermal.cpu_hot`, `thermal.cpu_throttling` |
| Slow CPU | Windows power plan > maximum processor state 50%, or the Power saver plan | `os.power_saver_plan`, `performance.cpu_limited` |
| CPU-limited game | Low resolution and low settings in a CPU-heavy game | `performance.cpu_limited` |
| GPU-limited game | High resolution and settings | `performance.gpu_limited` |
| Out of video memory | Maximum texture quality at high resolution on a card with little VRAM | `gpu.vram_exhausted`, `performance.stutter` |
| Out of RAM | Open many browser tabs before the game (close them after) | `memory.ram_exhausted` |
| Single-channel RAM | Power off, unplug, remove one stick, run, put it back | `memory.single_channel` |
| XMP off | Disable XMP/EXPO in the BIOS (this is the stock setting) | `memory.slow_speed` |
| Full drive | Fill a **non-system** test drive with large dummy files; delete them after | `storage.low_space` |
| Healthy baseline | A well-cooled PC in a normal game | no warnings |

Known-bad parts at the shop (a drive with bad sectors, a failing stick of RAM)
are the best cases of all - with the owner's OK, and with nothing of a
customer's on them.

## Recording a case

1. Change one thing only, and write down exactly what.
2. Run a capture: `PCDoctor.cmd -Mode Capture -Seconds 300 -Label "fan capped 40%"`.
3. Undo the change straight away and check the PC is back to normal.
4. Copy the run folder to `eval/cases/<short-name>/` and add a `label.json`:

   ```json
   {
     "expected": ["thermal.cpu_hot", "thermal.cpu_throttling"],
     "must_not": ["storage.disk_unhealthy"],
     "description": "CPU fan capped at 40%, 5 min Cinebench loop",
     "machine": "my desktop: Ryzen 7 5800X, RTX 3070"
   }
   ```

5. Run `python eval/run_eval.py --real-only` and record the score in
   [results.md](results.md).

Before committing a case, read its files once: they must contain no names and
no serial numbers (the collector's own test checks this, but you are the last
check).
