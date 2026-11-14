"""Train the LED reader and write weights plus a model card.

    python train.py --data data                  # real photos
    python train.py --data data-synth --epochs 3 # plumbing check on synth.py output

Writes to ``out/`` (git-ignored):

* ``leds.pt``          - the weights (after the last epoch; the test boards are
                         never looked at during training, so nothing is picked on them)
* ``model_card.json``  - data, split, settings, and the training numbers

The split is by board (see dataset.py) and the test boards are written into
the card, so evaluate.py scores exactly the boards training never saw.

Everything is seeded, so the same command on the same machine gives the same
model (different CPUs or library versions can still differ in the last decimals).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import platform
import random
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader

import model as led_model
from dataset import (
    CLASSES,
    IMAGE_SIZE,
    LedPhotos,
    class_counts,
    is_synthetic,
    list_samples,
    split_by_board,
)
from predict import DEFAULT_THRESHOLD

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "out"


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)


def train(
    data: Path,
    out: Path = DEFAULT_OUT,
    epochs: int = 15,
    batch_size: int = 32,
    lr: float = 3e-3,
    test_fraction: float = 0.25,
    threshold: float = DEFAULT_THRESHOLD,
    seed: int = 0,
    log=print,
) -> dict:
    """Train, save ``leds.pt`` and ``model_card.json`` in ``out``, return the card."""
    set_seed(seed)
    started = time.perf_counter()
    samples = list_samples(data)
    train_samples, test_samples = split_by_board(samples, test_fraction, seed)
    if not train_samples:
        raise ValueError(f"no training photos under {data}")

    train_set = LedPhotos(train_samples, augment=True, seed=seed)
    loader = DataLoader(
        train_set,
        batch_size=batch_size,
        shuffle=True,
        generator=torch.Generator().manual_seed(seed),
    )
    net = led_model.LedNet()
    optimiser = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=1e-4)
    loss_fn = nn.CrossEntropyLoss()

    history = []
    for epoch in range(1, epochs + 1):
        net.train()
        total, correct, loss_sum = 0, 0, 0.0
        for images, labels in loader:
            optimiser.zero_grad()
            logits = net(images)
            loss = loss_fn(logits, labels)
            loss.backward()
            optimiser.step()
            loss_sum += loss.item() * len(labels)
            correct += int((logits.argmax(1) == labels).sum())
            total += len(labels)
        row = {
            "epoch": epoch,
            "loss": round(loss_sum / total, 4),
            "train_accuracy": round(correct / total, 4),
        }
        history.append(row)
        log(f"epoch {epoch:3d}  loss {row['loss']:.4f}  train accuracy {row['train_accuracy']:.3f}")

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    led_model.save(net, out / "leds.pt", {"image_size": IMAGE_SIZE})
    synthetic = is_synthetic(data)
    card = {
        "model": "LedNet - small CNN from scratch, no pretrained weights",
        "parameters": led_model.count_parameters(net),
        "classes": list(CLASSES),
        "image_size": IMAGE_SIZE,
        "trained_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "data": {
            "folder": str(Path(data).resolve()),
            "synthetic": synthetic,
            "note": (
                "SYNTHETIC pictures from synth.py: every number here is a plumbing check, "
                "not a result."
                if synthetic
                else "Real photos. Scores are only as good as the labels and the board variety."
            ),
            "train_boards": sorted({s.board for s in train_samples}),
            "test_boards": sorted({s.board for s in test_samples}),
            "train_counts": class_counts(train_samples),
            "test_counts": class_counts(test_samples),
        },
        "settings": {
            "epochs": epochs,
            "batch_size": batch_size,
            "lr": lr,
            "test_fraction": test_fraction,
            "seed": seed,
        },
        "not_sure_threshold": threshold,
        "history": history,
        "train_seconds": round(time.perf_counter() - started, 1),
        "environment": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "machine": platform.machine(),
        },
    }
    (out / "model_card.json").write_text(json.dumps(card, indent=2) + "\n")
    log(f"wrote {out / 'leds.pt'} and {out / 'model_card.json'}")
    return card


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the debug-LED reader.")
    parser.add_argument("--data", type=Path, default=HERE / "data")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=3e-3)
    parser.add_argument("--test-fraction", type=float, default=0.25)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--threads", type=int, default=led_model.DEFAULT_THREADS)
    args = parser.parse_args()
    led_model.limit_threads(args.threads)
    train(
        args.data,
        args.out,
        args.epochs,
        args.batch_size,
        args.lr,
        args.test_fraction,
        args.threshold,
        args.seed,
    )


if __name__ == "__main__":
    main()
