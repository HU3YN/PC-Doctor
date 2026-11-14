"""synth -> train -> evaluate -> predict on a tiny synthetic set. Proves plumbing, not accuracy."""

import json

from dataset import CLASSES, list_samples
from evaluate import COLUMNS, evaluate, format_report, summarise
from predict import NOT_SURE, Reading, load_model, predict_paths
from synth import generate
from train import train


def test_summarise_counts_wrong_and_not_sure_separately():
    labels = [1, 1, 1, 2]
    readings = [
        Reading("cpu", 0.9, "cpu", "led_cpu"),
        Reading("vga", 0.9, "vga", "led_vga"),
        Reading(NOT_SURE, 0.4, "cpu", None),
        Reading("dram", 0.95, "dram", "led_dram"),
    ]
    s = summarise(labels, readings)
    assert s["per_class"]["cpu"] == {"right": 1, "wrong": 1, "not_sure": 1, "total": 3}
    assert s["per_class"]["dram"] == {"right": 1, "wrong": 0, "not_sure": 0, "total": 1}
    assert s["total"] == {"right": 2, "wrong": 1, "not_sure": 1, "total": 4}
    assert s["confusion"]["cpu"]["vga"] == 1
    assert "cpu: 1 of 3 right, 1 wrong, 1 not sure" in format_report(s)


def test_end_to_end_on_synthetic_photos(tmp_path):
    data, out = tmp_path / "data", tmp_path / "out"
    generate(data, boards=3, per_class=4, seed=0)
    card = train(
        data, out, epochs=2, batch_size=16, test_fraction=0.34, seed=0, log=lambda *_: None
    )

    assert (out / "leds.pt").exists()
    saved = json.loads((out / "model_card.json").read_text())
    assert saved == card
    assert saved["data"]["synthetic"] is True and "plumbing" in saved["data"]["note"]
    assert not set(saved["data"]["train_boards"]) & set(saved["data"]["test_boards"])

    summary = evaluate(out)
    assert summary["synthetic"] is True
    n_test = sum(saved["data"]["test_counts"].values())
    assert summary["total"]["total"] == n_test
    matrix_total = sum(sum(row[c] for c in COLUMNS) for row in summary["confusion"].values())
    assert matrix_total == n_test
    assert (out / "eval.json").exists()

    net, threshold = load_model(out)
    photos = [s.path for s in list_samples(data)[:3]]
    readings = predict_paths(photos, net, threshold)
    assert len(readings) == 3
    assert all(r.answer in (*CLASSES, NOT_SURE) for r in readings)
    # threshold above 1 can never be met: everything is "not sure"
    assert all(r.answer == NOT_SURE for r in predict_paths(photos, net, 1.01))


def test_training_is_repeatable(tmp_path):
    data = tmp_path / "data"
    generate(data, boards=2, per_class=2, seed=1)
    a = train(data, tmp_path / "a", epochs=1, batch_size=8, seed=0, log=lambda *_: None)
    b = train(data, tmp_path / "b", epochs=1, batch_size=8, seed=0, log=lambda *_: None)
    assert a["history"] == b["history"]
