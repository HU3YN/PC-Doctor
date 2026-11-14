"""Export the trained model to ONNX and check ONNX Runtime gives the same answers.

    python export_onnx.py            # out/model.pt -> out/model.onnx

ONNX is a file format for trained networks that many runtimes can load
without PyTorch: ONNX Runtime on Windows, Linux, phones, in C#, C++, ... The
analysis server could then run the model without installing PyTorch.

The exported model takes raw frame times in milliseconds, shape
(batch, 512), as float32, and returns one logit per window (input "frames_ms",
output "logit"). The batch size is free; the window length is fixed.

The check: the same windows go through PyTorch and through ONNX Runtime, and
the logits must agree within ``--atol`` (small float differences are normal:
the two use different maths libraries). The script exits with code 1 if not.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch

import model as frame_model
from dataset import WINDOW, make_synthetic, to_windows

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "out"


def export(net: torch.nn.Module, path: Path, window: int = WINDOW) -> None:
    net.eval()
    example = torch.full((2, window), 16.7)  # any input of the right shape will do
    # torch.export traces the network into a graph; "batch" says that axis 0
    # may be any size (without it the file would only accept batches of 2).
    batch = torch.export.Dim("batch")
    torch.onnx.export(
        net,
        (example,),
        str(path),
        input_names=["frames_ms"],
        output_names=["logit"],
        dynamic_shapes=({0: batch},),
        dynamo=True,  # the current exporter (needs the onnxscript package)
        external_data=False,  # keep the weights inside the one .onnx file
        verbose=False,
    )


def check(net: torch.nn.Module, path: Path, window: int = WINDOW, atol: float = 1e-4) -> dict:
    """Compare PyTorch and ONNX Runtime on synthetic windows, at a few batch sizes."""
    import onnx
    import onnxruntime as ort

    onnx.checker.check_model(onnx.load(str(path)))  # is the file well formed?
    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])

    windows = to_windows(make_synthetic(16, seed=99, n_frames=window * 4), window).frames
    worst = 0.0
    for batch in (1, 7, len(windows)):  # odd sizes too, to prove the batch axis is free
        x = windows[:batch]
        expected = frame_model.predict_logits(net, x)
        got = session.run(["logit"], {"frames_ms": x.astype(np.float32)})[0]
        worst = max(worst, float(np.abs(expected - got).max()))
    return {"max_abs_diff": worst, "atol": atol, "match": worst <= atol, "windows": len(windows)}


def main(argv: list[str] | None = None, log=print) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--atol", type=float, default=1e-4, help="allowed logit difference")
    args = parser.parse_args(argv)

    card = json.loads((args.out / "model_card.json").read_text(encoding="utf-8"))
    net = frame_model.load(str(args.out / card["weights"]))
    window = card["data_config"]["window"]
    path = args.out / "model.onnx"
    export(net, path, window)
    result = check(net, path, window, args.atol)
    (args.out / "onnx_check.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    verdict = "MATCH" if result["match"] else "MISMATCH"
    log(
        f"wrote {path}; ONNX Runtime vs PyTorch on {result['windows']} windows: "
        f"max |difference| {result['max_abs_diff']:.2e} (allowed {args.atol:g}) -> {verdict}"
    )
    return 0 if result["match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
