# ml

Two small models, each in its own folder with its own README and tests.

| Folder | What | Data so far |
|---|---|---|
| [`frames/`](frames/) | A 1-D CNN that marks stutter in frame-time windows, compared with the rules engine's `performance.stutter` rule on the same held-out windows; ONNX export and a CPU/GPU benchmark (Phases 5 and 8) | Synthetic only |
| [`leds/`](leds/) | A small CNN that reads which motherboard debug LED (CPU, DRAM, VGA, BOOT) is lit, with a "not sure" answer (Phase 10) | Synthetic only; not wired into the API |

Every number from synthetic data is a plumbing check, not a result. Real
numbers go in [docs/results.md](../docs/results.md) with the data set, its
size and the machine.

Each folder uses its own virtual environment so the large PyTorch install
stays out of the main one; [docs/testing.md](../docs/testing.md) has the
commands.
