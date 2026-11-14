"""Tests for dataset.py: the label definition, the generator, the split, real cases."""

from __future__ import annotations

import json

import numpy as np
import pytest
from pcdoctor_analysis import synth

import dataset as ds
from evaluate import rule_verdict

# ------------------------------------------------------------------ labels


@pytest.mark.parametrize(
    ("base", "frame", "expected"),
    [
        (16.7, 33.4, True),  # 60 FPS: twice as long and 16.7 ms extra
        (16.7, 30.0, False),  # 60 FPS: 13 ms extra, but under 2x
        (33.3, 66.6, True),  # 30 FPS: exactly 2x counts
        (4.17, 9.0, False),  # 240 FPS: 2.2x, but only 4.8 ms extra (the 8 ms floor)
        (4.17, 12.5, True),  # 240 FPS: 3x and 8.3 ms extra
    ],
)
def test_stutter_frame_definition(base, frame, expected):
    assert bool(ds.stutter_frames(np.array([frame]), np.array([base]))[0]) is expected


def test_window_label_is_any_stutter_frame():
    base = np.full(ds.WINDOW, 16.7)
    frames = base.copy()
    assert ds.window_label(frames, base) == 0
    frames[100] = 40.0
    assert ds.window_label(frames, base) == 1


def test_label_line_matches_the_rule_on_clear_cases():
    """On a steady series with clear spikes, the label and the real rule agree."""
    base = np.full(ds.WINDOW, 16.7)
    smooth = base * np.exp(np.random.default_rng(0).normal(0, 0.02, ds.WINDOW))
    spiky = smooth.copy()
    spiky[[100, 250, 400]] = 60.0
    assert ds.window_label(smooth, base) == 0 and rule_verdict(smooth) is False
    assert ds.window_label(spiky, base) == 1 and rule_verdict(spiky) is True


def test_rule_does_not_judge_short_windows():
    assert rule_verdict(np.full(100, 16.7)) is None


# --------------------------------------------------------------- generator


def test_generator_is_deterministic_and_prefix_stable():
    a = ds.make_synthetic(5, seed=3, n_frames=1024)
    b = ds.make_synthetic(20, seed=3, n_frames=1024)
    for x, y in zip(a, b[:5], strict=True):
        assert x.series_id == y.series_id and x.kind == y.kind
        np.testing.assert_array_equal(x.frame_ms, y.frame_ms)
    c = ds.make_synthetic(5, seed=4, n_frames=1024)
    assert not np.array_equal(a[0].frame_ms, c[0].frame_ms)


def test_every_kind_is_generated_and_in_range():
    series = ds.make_synthetic(len(ds.KINDS), seed=1, n_frames=2048)
    assert sorted(s.kind for s in series) == sorted(ds.KINDS)
    for s in series:
        assert s.frame_ms.min() >= ds.MIN_FRAME_MS and s.frame_ms.max() <= ds.MAX_FRAME_MS
        # base frame times stay within 30-240 FPS (plus the +-10% drift)
        assert s.base_ms.min() >= 1000 / 240 * 0.89 and s.base_ms.max() <= 1000 / 30 * 1.11


def test_hard_negatives_are_smooth_and_positives_have_stutter():
    series = ds.make_synthetic(len(ds.KINDS) * 30, seed=11, n_frames=2048)
    w = ds.to_windows(series)
    kinds = np.array(w.kinds)
    for kind in ds.HARD_NEGATIVE_KINDS:
        share = w.labels[kinds == kind].mean()
        assert share <= 0.01, f"{kind}: {share:.3f} of windows labeled stutter"
    for kind in ds.POSITIVE_KINDS:
        share = w.labels[kinds == kind].mean()
        # Not every window: events are random in place and size, some fall under the line.
        assert 0.1 <= share < 1.0, f"{kind}: {share:.3f}"


def test_unknown_kind_is_refused():
    with pytest.raises(ValueError):
        ds.synthetic_series(np.random.default_rng(0), "nope", 100, "x")


# ------------------------------------------------------------------ windows


def test_windows_shape_stride_and_short_series():
    series = ds.make_synthetic(3, seed=2, n_frames=2048)
    assert len(ds.to_windows(series)) == 3 * 4
    assert len(ds.to_windows(series, stride=ds.WINDOW // 2)) == 3 * 7
    w = ds.to_windows(series)
    assert w.frames.shape == (12, ds.WINDOW) and w.frames.dtype == np.float32
    short = ds.make_synthetic(1, seed=2, n_frames=ds.WINDOW - 1)
    assert len(ds.to_windows(short)) == 0


# -------------------------------------------------------------------- split


def test_split_is_by_series_with_no_leakage():
    config = ds.DataConfig(n_series=90, seed=5, n_frames=1024)
    series = ds.make_synthetic(config.n_series, config.seed, config.n_frames)
    train, val, test = ds.split_by_series(series, config.fractions, config.seed)
    ids = [{s.series_id for s in part} for part in (train, val, test)]
    assert not (ids[0] & ids[1]) and not (ids[0] & ids[2]) and not (ids[1] & ids[2])
    assert sum(len(i) for i in ids) == len(series)
    assert all(len(part) > 0 for part in (train, val, test))

    # And after cutting into (overlapping) windows, still no series in two parts.
    built = config.build()
    win_ids = {name: set(w.series_ids) for name, w in built.items()}
    assert not (win_ids["train"] & win_ids["val"])
    assert not (win_ids["train"] & win_ids["test"])
    assert not (win_ids["val"] & win_ids["test"])
    np.testing.assert_array_equal(config.test_windows().frames, built["test"].frames)


def test_split_does_not_depend_on_order():
    series = ds.make_synthetic(40, seed=6, n_frames=600)
    a = ds.split_by_series(series, seed=6)
    b = ds.split_by_series(series[::-1], seed=6)
    for x, y in zip(a, b, strict=True):
        assert {s.series_id for s in x} == {s.series_id for s in y}


def test_data_config_round_trips_through_json():
    config = ds.DataConfig(n_series=10, seed=9)
    again = ds.DataConfig.from_dict(json.loads(json.dumps(config.to_dict())))
    assert again == config


# --------------------------------------------------------------- real cases


def _case(root, name, sample, label):
    folder = sample.write(root / name)
    (folder / "label.json").write_text(json.dumps(label), encoding="utf-8")


def test_real_case_loader_with_fake_cases(tmp_path):
    # Real-format run folders, made by the analysis package's own sample generator.
    _case(tmp_path, "a_stutter", synth.stutter_vram(), {"expected": ["performance.stutter"]})
    _case(
        tmp_path, "b_smooth", synth.healthy(), {"expected": [], "must_not": ["performance.stutter"]}
    )
    # Says nothing about stutter: skipped.
    _case(tmp_path, "c_other", synth.healthy(), {"expected": ["thermal.cpu_hot"]})
    # No frame times at all: skipped.
    _case(tmp_path, "d_noframes", synth.whea_bluescreens(), {"expected": ["performance.stutter"]})

    cases = ds.load_real_cases(tmp_path)
    assert [(c.series_id, c.label) for c in cases] == [("real-a_stutter", 1), ("real-b_smooth", 0)]
    for c in cases:
        assert c.source == "real" and c.base_ms is None and len(c.frame_ms) > ds.WINDOW
    w = ds.to_windows(cases)
    assert len(w) > 0
    assert set(w.labels[np.array(w.series_ids) == "real-a_stutter"]) == {1}
    assert set(w.labels[np.array(w.series_ids) == "real-b_smooth"]) == {0}


def test_no_real_cases_is_fine(tmp_path):
    assert ds.load_real_cases(tmp_path) == []
    assert ds.load_real_cases(tmp_path / "missing") == []
