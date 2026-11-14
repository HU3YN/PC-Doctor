# ml/frames - a frame-time stutter model (Phase 5 and 8)

A small PyTorch 1-D CNN that reads a window of 512 frame times and says
"stutter" or "smooth". It is compared with the rules engine's own
`performance.stutter` rule on the same windows, exported to ONNX, and timed.

**Status: plumbing only.** It is trained and scored on synthetic data. There
are no real labeled captures yet, so there is no measured accuracy. See
[Plumbing checks, not results](#plumbing-checks-not-results) and
[Not verified](#not-verified).

## Files

| File | What it does |
|---|---|
| `dataset.py` | Synthetic frame-time generator, the label definition, the real-case loader (`eval/cases/`), the split by series, and cutting series into windows |
| `model.py` | `FrameCNN` (about 8,000 weights) and its input normalisation |
| `metrics.py` | Counts (N of M), precision and recall, the same for the model and the rule |
| `train.py` | Trains with a fixed seed. Writes `out/model.pt` and `out/model_card.json` |
| `evaluate.py` | Model **and** the real `performance.stutter` rule on the same held-out windows; `--real-only` |
| `export_onnx.py` | Writes `out/model.onnx` and checks ONNX Runtime matches PyTorch |
| `benchmark.py` | PyTorch vs ONNX Runtime, CPU (and GPU if present), batch 1/8/64/256, median and p95 |
| `tests/` | pytest, about 5-20 s on a CPU |

`out/` and `.venv/` are git-ignored.

## Set-up

Use a separate virtual environment here. Do not install torch into the repo's
shared `.venv`.

```bash
cd ml/frames
python -m venv .venv
# Linux:   . .venv/bin/activate        Windows:  .venv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU-only torch, ~200 MB
pip install -r requirements.txt -e ../../workers
```

Without the CPU index, `pip install torch` on Linux also downloads the CUDA
libraries, several GB. On Windows the default wheel is CPU-only. For a GPU,
use the CUDA index from pytorch.org instead.

## Run

From `ml/frames/`:

```bash
python train.py                     # about 1 minute on a 4-core CPU; --series/--epochs to change size
python evaluate.py                  # synthetic held-out set, plus eval/cases if there are any
python evaluate.py --real-only      # only real captures - the only number worth quoting
python export_onnx.py               # out/model.onnx, exit code 1 if ONNX Runtime disagrees
python benchmark.py                 # out/benchmark.json; --repeats 200 for steadier numbers
python -m pytest -q                 # tests
```

`train.py --threads N` sets how many CPU threads PyTorch uses (default 2, so it
does not take over a shared machine). `benchmark.py --threads 1 2` sets which
thread counts are timed (default: 1 and all cores).

## How it works

### The label

The generator knows each frame's *base* time: what the frame would take with no
stutter. A frame is a **stutter frame** when it took **at least 2x the base
and at least 8 ms longer**. A window is **stutter** if it contains at least one
stutter frame.

These are the same numbers the rule uses for a spike (`spike_ratio`,
`spike_min_extra_ms` in `workers/pcdoctor_analysis/model.py`). The rule has to
*estimate* the base from the median of the previous 30 frames. The generator
*knows* it. So the label means "what the rule is trying to catch", not "what
the rule says". If the label were the rule's own answer, the rule would score
100% and the comparison would be meaningless.

What follows from that:

- A change of frame rate (a new scene) is **not** stutter, because the base
  changes too. The rule still counts the first frame of the new level as one
  spike, and on a short window one spike is enough to fire it. That is where
  its false alarms on `fps_changes` come from.
- At 240 FPS the 8 ms floor dominates. A frame needs about 12.2 ms (nearly 3x)
  to count.
- Windows are 512 frames because the rule will not judge fewer than 300. On a
  window of 2-17 s, one spike is over the rule's "4 per minute" line, so on
  these windows both mean "at least one felt spike".

### Synthetic kinds

Base frame rates are 30-240 FPS with a slow drift, log-normal jitter, and
sometimes sudden changes of frame rate. On top of that, each series is one kind:

- **Usually stutter:** `hitches` (isolated long frames), `periodic_spikes`,
  `bursts` (3-12 slow frames in a row), `pacing_judder` (every 2nd-4th frame
  1.6-3.5x long). Event sizes are drawn around the line, so some fall below it
  and those windows are labeled smooth.
- **Hard negatives:** `noisy_smooth` (8-15% jitter), `fps_changes`,
  `tiny_blip` (one long frame under the line), `mild_pacing` (1.15-1.7x).
- `smooth`.

### Split

Windows from one series look alike. The split is done on **whole series**
(hashed id -> train 70% / val 15% / test 15%), and only after that are series
cut into windows. The training windows overlap; validation and test windows
do not. `tests/test_dataset.py` checks that no series appears in two parts.

### Real cases

`load_real_cases` reads `eval/cases/<name>/` (a collector run folder plus
`label.json`, the format `eval/run_eval.py` uses). It reads frame times with
the analysis package's own loader. The label is 1 if `performance.stutter` is
in `expected` and 0 if it is in `must_not`. Other cases are skipped. The label
covers the whole capture, so `evaluate.py --real-only` reports two views:

- **Per case:** the model says "stutter" if any window does. The rule runs once
  on the whole capture, as the analyzer does.
- **Per window:** each window inherits its case's label, which is rough.

Real cases are not used for training.

### The model

The input is raw milliseconds. The normalisation is inside the model, so the
ONNX file takes raw milliseconds too:

- channel 0 = `log(frame / window median)`: the shape, the same at any FPS
- channel 1 = `log(frame / 16.7 ms)`: the absolute size, needed for the 8 ms floor

Then three Conv1d layers with ReLU and one max-pool, global max and mean
pooling, and one linear layer that outputs a logit. `sigmoid(logit) >= 0.5`
means stutter. The loss is `BCEWithLogitsLoss` with `pos_weight` because
stutter windows are the minority, the optimiser is Adam, and the epoch with the
lowest validation loss is kept.

### The rule in `evaluate.py`

`rule_verdict` builds a `RunData` with a `FrameData` from the window's frame
times. It then calls the function registered as `performance.stutter` (looked
up by code in `pcdoctor_analysis.rules`), with default `Thresholds`. Nothing is
re-implemented. Like the model, the rule sees only the window, with no frames
before it.

## Plumbing checks, not results

**Every number below is a PLUMBING CHECK.** The scores come from synthetic
data that was written together with the label and the model. They prove the
scripts run and fit together. They are not the model's accuracy and must not
be quoted as results. The timings come from a shared 4-vCPU cloud VM with
other jobs running on it, so they prove that `benchmark.py` works and nothing
more.

Run of 2026-11-14 (`train.py` defaults: 600 series, 8 epochs, seed 1234, 2 threads):

```text
train  6810 windows, 1339 stutter / val 712, 158 / test 456, 123   (series split 70/15/15)
Synthetic test set: 456 windows from 57 series (PLUMBING CHECK - not a result)
  model  caught 123 of 123 stutter windows, false alarms on 3 of 333 smooth windows
  rule   caught 122 of 123 stutter windows, false alarms on 3 of 333 smooth windows
  model and rule agree on 449 of 456 windows
  (rule false alarms: 2 on fps_changes, 1 on smooth; model: 2 on bursts, 1 on hitches)
ONNX Runtime vs PyTorch on 64 windows: max |difference| 1.14e-05 (allowed 1e-4) -> MATCH
benchmark, CPU only (no GPU), median per call, batch 1 / 256:
  pytorch      1 thread  0.33 ms / 73 ms     2 threads 0.24 ms / 35 ms
  onnxruntime  1 thread  0.12 ms / 41 ms     2 threads 0.11 ms / 25 ms
```

On the same VM, an earlier PyTorch run with 4 threads was very slow and
erratic (around 100 ms for batch 1), because other jobs were using the cores.
This shows how much a shared machine distorts timings. It says nothing about
real PCs.

## Not verified

- **No real labeled captures exist yet** (`eval/cases/` is empty). There is no
  measured accuracy for the model or the rule on real games. The real-case
  loader and `--real-only` were tested only on fake cases built from
  `pcdoctor_analysis.synth` sample runs.
- **GPU not tested.** The build machine has no GPU. The CUDA paths in
  `benchmark.py` (PyTorch `cuda`, ONNX Runtime `CUDAExecutionProvider`) have
  never run.
- Timings on a real desktop or laptop have not been measured.
- Windows and macOS: `benchmark.py` has code to read CPU and RAM details there,
  but it has only run on Linux.
- Training is repeatable on the same machine with the same thread count. A
  different thread count or CPU can change the last decimals, and so the
  chosen epoch.
- Whether the label definition matches what players actually feel as stutter
  is an assumption. It copies the rule's thresholds, which are themselves
  starting values (docs/rules.md).
