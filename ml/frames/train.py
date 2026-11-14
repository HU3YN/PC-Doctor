"""Train the frame-time CNN on synthetic data and write weights plus a model card.

    python train.py                          # default size, a few minutes on a CPU
    python train.py --series 120 --epochs 2  # a quick plumbing run

Writes to ``out/`` (git-ignored):

* ``model.pt``         - the weights (the epoch with the lowest validation loss)
* ``model_card.json``  - what the model was trained on, how, and how it scored

Everything is seeded, so the same command on the same machine gives the same
model. (Different CPUs or library versions can still differ in the last
decimals.)

The scores in the model card are on *synthetic* windows. They show that the
pipeline works; they say nothing about real games. See README.md.
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

import model as frame_model
from dataset import DataConfig, Windows
from metrics import score

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "out"


def set_seed(seed: int) -> None:
    """Seed every random number generator the training touches."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    # Ask PyTorch to pick only operations that give the same result every run.
    torch.use_deterministic_algorithms(True)


def evaluate_split(net: nn.Module, windows: Windows, loss_fn: nn.Module) -> dict:
    """Loss and counts on one split (threshold 0.5)."""
    logits = frame_model.predict_logits(net, windows.frames)
    loss = float(loss_fn(torch.as_tensor(logits), torch.as_tensor(windows.labels).float()))
    result = score(windows.labels, logits >= 0.0)  # logit 0 = probability 0.5
    result["loss"] = round(loss, 5)
    return result


def train(
    config: DataConfig,
    epochs: int = 8,
    batch_size: int = 64,
    lr: float = 2e-3,
    width: int = 32,
    seed: int = 1234,
    out_dir: Path = DEFAULT_OUT,
    log=print,
    threads: int | None = 2,
) -> dict:
    """Train, save the best epoch, write the model card. Returns the card."""
    started = time.perf_counter()
    set_seed(seed)
    if threads:
        # CPU threads PyTorch may use. Capped (default 2) so training does not
        # take over a shared machine; this tiny model gains little from more.
        torch.set_num_threads(threads)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = config.build()
    train_set, val_set, test_set = data["train"], data["val"], data["test"]
    for name, w in data.items():
        log(f"{name:<5} {len(w):6d} windows, {w.positives:6d} stutter")
    if len(train_set) == 0 or len(val_set) == 0:
        raise SystemExit("Not enough series for a train and a validation split; use more.")

    net = frame_model.FrameCNN(width=width)
    log(f"model: {frame_model.count_parameters(net)} parameters")

    # Stutter and smooth windows are not equally common. pos_weight makes a
    # missed stutter window cost as much in total as all the smooth ones, so
    # the model cannot score well by always answering "smooth".
    positives = max(train_set.positives, 1)
    negatives = max(len(train_set) - train_set.positives, 1)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor(negatives / positives))
    optimiser = torch.optim.Adam(net.parameters(), lr=lr)

    x_all = torch.as_tensor(train_set.frames)
    y_all = torch.as_tensor(train_set.labels, dtype=torch.float32)
    shuffle = torch.Generator().manual_seed(seed)  # its own generator: same order every run

    best_loss, best_epoch, history = float("inf"), -1, []
    weights_path = out_dir / "model.pt"
    for epoch in range(1, epochs + 1):
        net.train()
        order = torch.randperm(len(x_all), generator=shuffle)
        running = 0.0
        for start in range(0, len(order), batch_size):
            idx = order[start : start + batch_size]
            # The five lines every PyTorch training loop has:
            optimiser.zero_grad()  # forget the previous batch's gradients
            logits = net(x_all[idx])  # forward pass
            loss = loss_fn(logits, y_all[idx])  # how wrong
            loss.backward()  # gradients: which way to move each weight
            optimiser.step()  # move the weights a little that way
            running += loss.item() * len(idx)  # .item(): the plain number
        val = evaluate_split(net, val_set, loss_fn)
        train_loss = running / len(order)
        history.append({"epoch": epoch, "train_loss": round(train_loss, 5), "val": val})
        log(
            f"epoch {epoch:2d}  train loss {train_loss:.4f}  val loss {val['loss']:.4f}  "
            f"val caught {val['caught']}, false alarms {val['false_alarms']}"
        )
        if val["loss"] < best_loss:  # keep the epoch that did best on unseen data
            best_loss, best_epoch = val["loss"], epoch
            frame_model.save(net, str(weights_path), width)

    best = frame_model.load(str(weights_path))
    card = {
        "model": "FrameCNN (1-D CNN over frame-time windows)",
        "IMPORTANT": (
            "Trained and scored on SYNTHETIC data only. These numbers are a plumbing "
            "check, not a measure of how the model does on real games."
        ),
        "data": "synthetic",
        "created": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seed": seed,
        "data_config": config.to_dict(),
        "label_definition": (
            "A window is 'stutter' when at least one frame took >= 2x the generator's "
            "known base frame time AND >= 8 ms longer (see dataset.py)."
        ),
        "sizes": {
            name: {"windows": len(w), "stutter": w.positives, "series": len(set(w.series_ids))}
            for name, w in data.items()
        },
        "training": {
            "epochs": epochs,
            "best_epoch": best_epoch,
            "batch_size": batch_size,
            "learning_rate": lr,
            "threads": torch.get_num_threads(),
            "width": width,
            "parameters": frame_model.count_parameters(best),
            "seconds": round(time.perf_counter() - started, 1),
            "torch": torch.__version__,
            "python": platform.python_version(),
        },
        "threshold": 0.5,
        "metrics_synthetic": {
            "val": evaluate_split(best, val_set, loss_fn),
            "test": evaluate_split(best, test_set, loss_fn),
        },
        "history": history,
        "weights": weights_path.name,
    }
    (out_dir / "model_card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    log(f"best epoch {best_epoch}; wrote {weights_path} and model_card.json")
    log(
        f"synthetic test: caught {card['metrics_synthetic']['test']['caught']}, "
        f"false alarms {card['metrics_synthetic']['test']['false_alarms']} (plumbing check)"
    )
    return card


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--series", type=int, default=DataConfig.n_series, help="synthetic series")
    parser.add_argument("--frames", type=int, default=DataConfig.n_frames, help="frames per series")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=2e-3)
    parser.add_argument("--width", type=int, default=32, help="channels in the CNN")
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--threads", type=int, default=2, help="CPU threads for PyTorch")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    config = DataConfig(n_series=args.series, seed=args.seed, n_frames=args.frames)
    train(
        config,
        args.epochs,
        args.batch_size,
        args.lr,
        args.width,
        args.seed,
        args.out,
        threads=args.threads,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
