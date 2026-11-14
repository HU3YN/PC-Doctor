"""Frame-time windows labeled "stutter" or "smooth".

A *series* is one capture: a list of frame times in milliseconds, one per
frame, in the order the frames were shown. A *window* is a fixed-length slice
of a series (``WINDOW`` frames). The model looks at one window at a time and
answers "does this window contain stutter?".

Two sources of series:

1. ``synthetic_series`` - a generator. Every synthetic series knows its own
   *base* frame time: what each frame would have taken with no stutter (the
   scene's real frame rate, which may drift or change). That lets us label
   each window exactly, with the definition below.
2. ``load_real_cases`` - real captures in ``eval/cases/<name>/`` (a collector
   run folder plus a ``label.json``). There are none yet. A real capture has
   no known base, so its label is the case's label for the whole capture
   (see ``load_real_cases``).

The label definition (synthetic data)
-------------------------------------
A frame is a **stutter frame** when it took

* at least ``SPIKE_RATIO`` (2x) the base frame time, **and**
* at least ``SPIKE_MIN_EXTRA_MS`` (8 ms) longer than the base frame time.

A window is labeled **stutter (1)** when it contains at least one stutter
frame, else **smooth (0)**.

This is the same line the real ``performance.stutter`` rule draws for a
"spike" (``Thresholds.spike_ratio`` and ``Thresholds.spike_min_extra_ms`` in
``workers/pcdoctor_analysis/model.py``), with one difference on purpose: the
rule has to *estimate* the base from the median of the previous 30 frames,
while the generator *knows* it. So the label is "what the rule is trying to
catch", not "what the rule says" - otherwise the rule would score 100% by
construction and the comparison would mean nothing.

Consequences, written down so nobody is surprised:

* A change of frame rate (a new scene, 200 -> 60 FPS) is **not** stutter: the
  base changes with it. The rule agrees in spirit (its "level shift" logic),
  but it still counts the first frame of the new level as a spike.
* At high FPS the 8 ms floor dominates: at 240 FPS (4.2 ms) a frame must take
  about 12.2 ms - nearly 3x - to count.
* A short window makes one spike a lot "per minute": with 512 frames at
  120 FPS (4.3 s), one spike is 14 per minute, over the rule's 4-per-minute
  line. So on windows this short, both the rule and the label mean "at least
  one felt spike".

Splitting
---------
Windows from one series look alike (same frame rate, same noise). If windows
of one series landed in both training and test data, the test score would be
too kind. So ``split_by_series`` splits whole series, and only then cuts them
into windows. ``tests/test_dataset.py`` checks that no series is in two parts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# Frames per window. 512 and not 256 because the real rule refuses to judge
# fewer than 300 frames (Thresholds.min_frames_for_stats); with 512 it can be
# run with its default settings on exactly the windows the model sees.
WINDOW = 512

# The same numbers as the rule's spike definition (pcdoctor_analysis Thresholds).
SPIKE_RATIO = 2.0
SPIKE_MIN_EXTRA_MS = 8.0

# Frame times are clipped to this range so a broken capture cannot produce
# zeros (log of 0) or absurd values. 1000 ms = a one-second freeze.
MIN_FRAME_MS = 0.5
MAX_FRAME_MS = 1000.0

# The kinds of synthetic series. "Hard negatives" are made to look a bit like
# stutter without being stutter, so the model cannot just learn "noisy = bad".
POSITIVE_KINDS = ("hitches", "periodic_spikes", "bursts", "pacing_judder")
HARD_NEGATIVE_KINDS = ("noisy_smooth", "fps_changes", "tiny_blip", "mild_pacing")
KINDS = ("smooth", *HARD_NEGATIVE_KINDS, *POSITIVE_KINDS)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES_DIR = REPO_ROOT / "eval" / "cases"


@dataclass
class Series:
    """One capture's frame times, plus what we know about it."""

    series_id: str  # unique; the split is done on this
    kind: str  # synthetic kind, or "real"
    frame_ms: np.ndarray  # shape (n,), float64
    base_ms: np.ndarray | None = None  # synthetic only: the no-stutter frame time
    label: int | None = None  # real only: the case's label for the whole capture
    source: str = "synthetic"  # "synthetic" or "real"


@dataclass
class Windows:
    """Many windows stacked into arrays, ready for PyTorch."""

    frames: np.ndarray  # shape (N, WINDOW), float32, raw milliseconds
    labels: np.ndarray  # shape (N,), int64, 1 = stutter
    series_ids: list[str] = field(default_factory=list)  # which series each came from
    kinds: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.labels)

    @property
    def positives(self) -> int:
        return int(self.labels.sum())


# --------------------------------------------------------------------- labels


def stutter_frames(frame_ms: np.ndarray, base_ms: np.ndarray) -> np.ndarray:
    """True for every frame that is a stutter frame (see the module docstring)."""
    extra = frame_ms - base_ms
    return (frame_ms >= SPIKE_RATIO * base_ms) & (extra >= SPIKE_MIN_EXTRA_MS)


def window_label(frame_ms: np.ndarray, base_ms: np.ndarray) -> int:
    """1 if the window holds at least one stutter frame, else 0."""
    return int(stutter_frames(frame_ms, base_ms).any())


# ------------------------------------------------------------------ generator


def _event_threshold_ms(base: float) -> float:
    """How much extra time a frame needs to count as stutter at this base.

    ``frame >= 2 * base`` means ``extra >= base``; the floor is 8 ms. So the
    line is ``max(base, 8)``. Events are drawn around this line - some above,
    some below - so the model has to learn where the line is.
    """
    return max((SPIKE_RATIO - 1.0) * base, SPIKE_MIN_EXTRA_MS)


def _base_curve(rng: np.random.Generator, n: int, kind: str) -> np.ndarray:
    """The no-stutter frame time of every frame: a frame rate that drifts slowly."""
    fps = rng.uniform(30.0, 240.0)
    t = np.arange(n)
    # A slow drift of up to +-10%, like a camera moving through a scene.
    period = rng.uniform(800.0, 4000.0)
    drift = 1.0 + rng.uniform(0.0, 0.10) * np.sin(2 * np.pi * t / period + rng.uniform(0, 6.3))
    base = (1000.0 / fps) * drift
    if kind == "fps_changes" or rng.random() < 0.15:
        # Sudden changes of frame rate (a new scene, a menu, a cutscene).
        # The base itself jumps, so these are *not* stutter by the definition.
        for _ in range(rng.integers(1, 4)):
            start = int(rng.integers(0, n))
            new_fps = rng.uniform(30.0, 240.0)
            base[start:] = (1000.0 / new_fps) * drift[start:]
    return base


def _add_spike(
    frames: np.ndarray, base: np.ndarray, i: int, rng: np.random.Generator, low: float, high: float
) -> None:
    """Make frame ``i`` longer by ``low..high`` times the stutter line at that frame."""
    line = _event_threshold_ms(float(base[i]))
    # Log-uniform: as many small spikes as big ones, on a ratio scale.
    factor = float(np.exp(rng.uniform(np.log(low), np.log(high))))
    frames[i] = base[i] + line * factor


def synthetic_series(rng: np.random.Generator, kind: str, n_frames: int, series_id: str) -> Series:
    """Generate one synthetic series of ``kind``. Deterministic for a given ``rng`` state."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; choose from {KINDS}")
    base = _base_curve(rng, n_frames, kind)

    # Frame-to-frame jitter: every frame is a little off its base. Multiplicative
    # (log-normal) because real jitter grows with the frame time.
    sigma = rng.uniform(0.08, 0.15) if kind == "noisy_smooth" else rng.uniform(0.005, 0.06)
    frames = base * np.exp(rng.normal(0.0, sigma, n_frames))

    if kind == "hitches":
        # A few isolated long frames (loading, shader compile, a disk read).
        # Sizes from 0.5x to 15x the stutter line: some fall below it.
        for i in rng.integers(0, n_frames, size=rng.integers(1, 8)):
            _add_spike(frames, base, int(i), rng, 0.5, 15.0)
    elif kind == "periodic_spikes":
        # A spike every `every` frames, all about the same size (a background
        # task waking up on a timer, a polling driver).
        every = int(rng.integers(20, 400))
        factor = float(np.exp(rng.uniform(np.log(0.6), np.log(6.0))))
        for i in range(int(rng.integers(0, every)), n_frames, every):
            _add_spike(frames, base, i, rng, factor * 0.9, factor * 1.1)
    elif kind == "bursts":
        # A few runs of 3-12 slow frames in a row (streaming in an area).
        for start in rng.integers(0, n_frames, size=rng.integers(1, 5)):
            length = int(rng.integers(3, 13))
            factor = float(np.exp(rng.uniform(np.log(0.6), np.log(6.0))))
            for i in range(int(start), min(n_frames, int(start) + length)):
                _add_spike(frames, base, i, rng, factor * 0.8, factor * 1.2)
    elif kind in ("pacing_judder", "mild_pacing"):
        # Uneven pacing: in a stretch of the series every m-th frame is k times
        # the base (e.g. 16.7, 16.7, 33.3 ms - the classic V-sync judder).
        # "mild_pacing" keeps k small, so it is a hard negative.
        m = int(rng.integers(2, 5))
        k = rng.uniform(1.15, 1.7) if kind == "mild_pacing" else rng.uniform(1.6, 3.5)
        start = int(rng.integers(0, n_frames // 2))
        stop = int(rng.integers(start + n_frames // 4, n_frames + 1))
        frames[start:stop:m] = base[start:stop:m] * k * np.exp(rng.normal(0, 0.02))
    elif kind == "tiny_blip":
        # One small long frame, clearly below the line: a hard negative.
        _add_spike(frames, base, int(rng.integers(0, n_frames)), rng, 0.2, 0.8)
    # "smooth", "noisy_smooth" and "fps_changes" add nothing more.

    frames = np.clip(frames, MIN_FRAME_MS, MAX_FRAME_MS)
    return Series(series_id=series_id, kind=kind, frame_ms=frames, base_ms=base)


def make_synthetic(n_series: int, seed: int, n_frames: int = 4096) -> list[Series]:
    """``n_series`` synthetic series, kinds in turn, all from one seed.

    Each series gets its own random generator derived from (seed, index), so
    series 7 is the same whether you make 10 series or 1000.
    """
    out = []
    for index in range(n_series):
        rng = np.random.default_rng([seed, index])
        kind = KINDS[index % len(KINDS)]
        out.append(synthetic_series(rng, kind, n_frames, series_id=f"syn-{seed}-{index:05d}"))
    return out


# ----------------------------------------------------------------- real cases


def load_real_cases(cases_dir: str | Path = DEFAULT_CASES_DIR) -> list[Series]:
    """Real captures from ``eval/cases/<name>/`` (the format ``eval/run_eval.py`` uses).

    A case is a collector run folder with a ``label.json``::

        {"expected": ["performance.stutter"], "must_not": [...], "description": "..."}

    The frame times come from the folder's ``presentmon.csv``, read by the
    analysis package's own loader (``pcdoctor_analysis.load_run_dir``), so they
    are exactly what the rules see.

    Label: 1 when ``performance.stutter`` is in "expected", 0 when it is in
    "must_not". A case that names it in neither says nothing about stutter and
    is skipped, as is a case without frame times.

    The label belongs to the whole capture. When a capture is cut into
    windows, every window inherits it - which is only roughly true (a stutter
    capture has smooth stretches too). So real windows are used for
    evaluation, reported per case as well as per window, and not for training.
    """
    from pcdoctor_analysis import load_run_dir  # the workers package

    root = Path(cases_dir)
    out: list[Series] = []
    for label_file in sorted(root.glob("*/label.json")):
        label_doc = json.loads(label_file.read_text(encoding="utf-8"))
        expected = label_doc.get("expected", []) or []
        must_not = label_doc.get("must_not", []) or []
        if "performance.stutter" in expected:
            label = 1
        elif "performance.stutter" in must_not:
            label = 0
        else:
            continue
        run = load_run_dir(label_file.parent)
        if run.frames is None or not run.frames.frame_times_ms:
            continue
        frames = np.clip(np.asarray(run.frames.frame_times_ms, dtype=np.float64), 0, MAX_FRAME_MS)
        frames = np.maximum(frames, MIN_FRAME_MS)
        out.append(
            Series(
                series_id=f"real-{label_file.parent.name}",
                kind="real",
                frame_ms=frames,
                label=label,
                source="real",
            )
        )
    return out


# ------------------------------------------------------------ split, windows


def split_by_series(
    series: list[Series], fractions: tuple[float, float, float] = (0.7, 0.15, 0.15), seed: int = 0
) -> tuple[list[Series], list[Series], list[Series]]:
    """Split into (train, validation, test) by whole series.

    Each series id is hashed together with the seed to a number in [0, 1); that
    number decides its part. The same id always lands in the same part, no
    matter how many other series there are or what order they come in.
    """
    if abs(sum(fractions) - 1.0) > 1e-9:
        raise ValueError("fractions must add up to 1")
    parts: tuple[list[Series], list[Series], list[Series]] = ([], [], [])
    for s in series:
        digest = hashlib.sha256(f"{seed}:{s.series_id}".encode()).digest()
        u = int.from_bytes(digest[:8], "big") / 2**64
        if u < fractions[0]:
            parts[0].append(s)
        elif u < fractions[0] + fractions[1]:
            parts[1].append(s)
        else:
            parts[2].append(s)
    return parts


def to_windows(series: list[Series], window: int = WINDOW, stride: int | None = None) -> Windows:
    """Cut every series into windows of ``window`` frames, ``stride`` frames apart.

    ``stride`` defaults to ``window`` (no overlap). A series shorter than one
    window gives nothing; the leftover frames at the end are dropped.
    """
    stride = stride or window
    frames, labels, ids, kinds = [], [], [], []
    for s in series:
        for start in range(0, len(s.frame_ms) - window + 1, stride):
            chunk = s.frame_ms[start : start + window]
            if s.base_ms is not None:
                label = window_label(chunk, s.base_ms[start : start + window])
            elif s.label is not None:
                label = s.label
            else:
                raise ValueError(f"series {s.series_id} has neither a base nor a label")
            frames.append(chunk)
            labels.append(label)
            ids.append(s.series_id)
            kinds.append(s.kind)
    if not frames:
        return Windows(np.zeros((0, window), np.float32), np.zeros(0, np.int64), [], [])
    return Windows(
        frames=np.asarray(frames, dtype=np.float32),
        labels=np.asarray(labels, dtype=np.int64),
        series_ids=ids,
        kinds=kinds,
    )


@dataclass
class DataConfig:
    """Everything needed to rebuild the exact same synthetic data set.

    It is stored in the model card, so ``evaluate.py`` can rebuild the same
    held-out (test) series the model never saw.
    """

    n_series: int = 600
    seed: int = 1234
    n_frames: int = 4096
    window: int = WINDOW
    train_stride: int = WINDOW // 2  # overlapping windows = more training examples
    fractions: tuple[float, float, float] = (0.7, 0.15, 0.15)

    def build(self) -> dict[str, Windows]:
        """The train / val / test windows. Val and test use no overlap."""
        series = make_synthetic(self.n_series, self.seed, self.n_frames)
        train, val, test = split_by_series(series, self.fractions, self.seed)
        return {
            "train": to_windows(train, self.window, self.train_stride),
            "val": to_windows(val, self.window),
            "test": to_windows(test, self.window),
        }

    def test_windows(self) -> Windows:
        """Only the held-out test windows (what ``evaluate.py`` needs)."""
        series = make_synthetic(self.n_series, self.seed, self.n_frames)
        return to_windows(split_by_series(series, self.fractions, self.seed)[2], self.window)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["fractions"] = list(self.fractions)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> DataConfig:
        d = dict(d)
        d["fractions"] = tuple(d["fractions"])
        return cls(**d)
