"""End to end on a tiny budget: train -> evaluate -> export ONNX -> benchmark.

Small enough to run in seconds on a CPU. It proves the scripts fit together,
not that the model is any good.
"""

from __future__ import annotations

import getpass
import json
import socket

import pytest
from pcdoctor_analysis import synth

import benchmark
import evaluate
import export_onnx
import train
from dataset import DataConfig


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    out = tmp_path_factory.mktemp("out")
    config = DataConfig(n_series=45, seed=3, n_frames=1024)
    card = train.train(
        config, epochs=1, batch_size=32, width=8, seed=3, out_dir=out, log=lambda *_: None
    )
    return out, card


def test_train_writes_weights_and_card(trained):
    out, card = trained
    assert (out / "model.pt").is_file()
    on_disk = json.loads((out / "model_card.json").read_text())
    assert on_disk == json.loads(json.dumps(card))
    assert card["data"] == "synthetic" and card["seed"] == 3
    assert "SYNTHETIC" in card["IMPORTANT"]
    for part in ("train", "val", "test"):
        assert card["sizes"][part]["windows"] > 0
    assert {"precision", "recall", "caught"} <= set(card["metrics_synthetic"]["test"])
    assert card["created"].endswith("Z")


def test_train_is_repeatable(trained, tmp_path):
    out, card = trained
    config = DataConfig.from_dict(card["data_config"])
    again = train.train(
        config, epochs=1, batch_size=32, width=8, seed=3, out_dir=tmp_path, log=lambda *_: None
    )
    assert again["metrics_synthetic"] == card["metrics_synthetic"]


def test_evaluate_scores_model_and_rule_on_the_same_windows(trained, tmp_path):
    out, _ = trained
    lines = []
    assert evaluate.main(["--out", str(out), "--cases", str(tmp_path)], log=lines.append) == 0
    report = json.loads((out / "eval.json").read_text())
    syn = report["synthetic"]
    assert syn["PLUMBING_CHECK_ONLY"] is True
    assert syn["model"]["windows"] == syn["rule"]["windows"] > 0
    assert syn["model"]["stutter_windows"] == syn["rule"]["stutter_windows"]
    assert report["real"] == {"cases": 0}
    assert any("PLUMBING CHECK" in line for line in lines)


def test_evaluate_real_only_with_a_fake_case(trained, tmp_path):
    out, _ = trained
    for name, sample, label in [
        ("stutter", synth.stutter_vram(), {"expected": ["performance.stutter"]}),
        ("smooth", synth.healthy(), {"must_not": ["performance.stutter"]}),
    ]:
        folder = sample.write(tmp_path / name)
        (folder / "label.json").write_text(json.dumps(label))
    lines = []
    assert (
        evaluate.main(
            ["--out", str(out), "--cases", str(tmp_path), "--real-only"], log=lines.append
        )
        == 0
    )
    report = json.loads((out / "eval_real.json").read_text())
    assert "synthetic" not in report
    real = report["real"]
    assert real["cases"] == 2
    rows = {r["case"]: r for r in real["per_case"]["rows"]}
    # The analyzer's own sample cases: the rule must get them right on the whole capture.
    assert rows["real-stutter"]["rule"] is True and rows["real-smooth"]["rule"] is False


def test_export_onnx_matches_pytorch(trained):
    out, _ = trained
    assert export_onnx.main(["--out", str(out)], log=lambda *_: None) == 0
    check = json.loads((out / "onnx_check.json").read_text())
    assert check["match"] and check["max_abs_diff"] <= 1e-4


def test_benchmark_names_hardware_only(trained):
    out, _ = trained
    report = benchmark.run(out, batch_sizes=(1, 4), repeats=2, threads=[1, 2], log=lambda *_: None)
    assert {r["engine"] for r in report["results"]} == {"pytorch", "onnxruntime"}
    for r in report["results"]:
        assert r["median_ms"] > 0 and r["p95_ms"] >= r["median_ms"]
    assert set(report["machine"]) == {
        "cpu_model",
        "logical_cores",
        "physical_cores",
        "ram_gb",
        "gpu_model",
        "os",
        "arch",
    }
    text = (out / "benchmark.json").read_text()
    for private in (socket.gethostname(), getpass.getuser()):
        if len(private) >= 3:
            assert private not in text
