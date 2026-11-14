# ml/leds - debug-LED reader (Phase 10)

Reads a photo of a motherboard's four debug LEDs (CPU, DRAM, VGA, BOOT) and
says which one is lit - or "not sure". The classes match the no-boot guide
(`/api/noboot`, `workers/pcdoctor_analysis/noboot.py`):

| Class | Meaning | No-boot guide code |
|---|---|---|
| `none` | no debug LED lit | - |
| `cpu` | CPU LED stays on | `led_cpu` |
| `dram` | DRAM LED stays on | `led_dram` |
| `vga` | VGA LED stays on | `led_vga` |
| `boot` | BOOT LED stays on | `led_boot` |

**Not wired into the API.** It should only be once it has been measured on
real photos of real boards (see "Not verified" below). Until then the photo
intake keeps working as it does today.

## Files

| File | What it does |
|---|---|
| `dataset.py` | Finds photos in `data/<board_id>/<class>/`, splits **by board**, loads them as tensors |
| `synth.py` | Draws fake LED photos - for testing the plumbing only |
| `model.py` | `LedNet`, a small CNN trained from scratch (about 17 thousand weights, no pretrained weights) |
| `train.py` | Seeded training; writes `out/leds.pt` and `out/model_card.json` |
| `evaluate.py` | Scores the test boards: per class "N of M right", wrong, "not sure", confusion matrix; writes `out/eval.json` |
| `predict.py` | Reads photos; below the confidence threshold it answers "not sure" instead of guessing |
| `tests/` | pytest, CPU only, under a minute |

`out/`, `data/` and `data-synth/` are git-ignored. Real photos are never
committed unless the owner decides to.

## Photos: how to take and label them

```
data/
  <board_id>/            one folder per physical board, e.g. asus-b550f-01
    none/  cpu/  dram/  vga/  boot/
      *.jpg
```

- `board_id` is one physical board (two boards of the same model are two
  ids). The split is by board, so the test score is on boards the model never
  saw - photos of one board look alike and would otherwise inflate it.
- Frame the four LEDs and their printed labels; fill most of the photo with
  that strip. Square-ish crops work best (photos are resized to 96x96).
- Vary what a user would vary: distance, angle, room light, phone flash on and
  off, a bit of blur.
- Label by the LED that is lit **and stays lit**. During a normal boot the LEDs
  step through CPU -> DRAM -> VGA -> BOOT quickly; photograph the board when it
  has stopped on one. `none` = all off (booted, or no debug LEDs lit).
- **No people, faces or hands with rings/tattoos, and no serial-number or
  warranty stickers in frame.** Crop them out before saving. No EXIF location:
  strip metadata (most phone "share" options can) before copying photos here.
- Aim for many boards rather than many photos of one board. A few dozen photos
  per class per board is plenty; ten boards is a minimum before trusting a score.

## Commands

Set up (CPU torch is enough and much smaller):

```bash
python -m venv ml/leds/.venv
ml/leds/.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
ml/leds/.venv/bin/pip install -r ml/leds/requirements.txt
```

Run, from `ml/leds/`:

```bash
python synth.py                              # data-synth/: 8 fake boards x 5 classes x 30
python train.py --data data-synth           # plumbing check, ~2 min
python evaluate.py                           # test boards from out/model_card.json
python predict.py some-photo.jpg             # one JSON line per photo

python train.py --data data                  # real photos
python evaluate.py --data more-boards/       # score other boards (refuses training boards)
python predict.py --threshold 0.9 photo.jpg  # stricter "not sure"
```

Test and lint:

```bash
cd ml/leds && python -m pytest -q
ruff check ml/leds && ruff format --check ml/leds
```

## The "not sure" threshold

`predict.py` takes the top softmax probability. Below the threshold (default
0.8, stored in the model card) it answers `not sure` and reports the best
guess separately. `evaluate.py` counts a wrong answer and a "not sure"
separately: "not sure" sends the user to the manual checklist, a wrong answer
sends them to the wrong part. The threshold should be tuned on real
held-out boards - higher means fewer wrong answers and more "not sure".

## Plumbing check (synthetic - not a result)

`synth.py` -> `train.py --data data-synth` (15 epochs, about 2 minutes on 2 CPU
threads) -> `evaluate.py` -> `predict.py` was run
once on synthetic pictures to prove the code runs end to end. The numbers
are in `out/` on that machine and are deliberately not quoted here as
accuracy: a model scoring well on pictures drawn by `synth.py` has learnt
`synth.py`, nothing about real boards. (On the two unseen synthetic boards it
answered most DRAM and VGA pictures "not sure" - the threshold did its job,
and nothing here was tuned to make the fake numbers look better.)

Every script takes `--threads` (default 2) so it does not take every core of a
shared machine; the tests use 2 threads too.

## Not verified

- **No real photos have been collected, so nothing about real accuracy is
  known.** No score from this folder may be quoted until `evaluate.py` has
  run on real held-out boards.
- Whether 96x96 is enough resolution for a small LED in a phone photo taken
  from a normal distance (it may need a crop step first).
- How the reader handles boards with a 2-digit Q-code display instead of, or as
  well as, LEDs; LEDs in other colours; RGB lighting near the LEDs; LEDs
  photographed mid-boot.
- The 0.8 threshold is a starting value, not tuned.
- Not run on Windows; not run on a GPU (CPU only).
- Not wired into the API, the web app or the bot.
