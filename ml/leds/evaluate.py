"""Score the trained reader on the test boards (the ones training never saw).

    python evaluate.py                     # boards and data folder from out/model_card.json
    python evaluate.py --data other-photos # every photo in another folder

Prints, per class, "N of M right" plus how many were wrong and how many were
"not sure", and a confusion matrix whose last column is "not sure". A wrong
answer and a "not sure" are counted separately: a reader that says "not sure"
is honest, one that names the wrong LED sends someone to the wrong part.
Writes ``out/eval.json``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

import model as led_model
from dataset import CLASSES, is_synthetic, list_samples, load_image, split_on_boards
from predict import DEFAULT_OUT, NOT_SURE, Reading, decide, load_model

COLUMNS = (*CLASSES, NOT_SURE)


def summarise(true_labels: list[int], readings: list[Reading]) -> dict:
    """Per-class counts and the confusion matrix (rows = truth, columns = answer)."""
    matrix = {t: dict.fromkeys(COLUMNS, 0) for t in CLASSES}
    for label, reading in zip(true_labels, readings, strict=True):
        matrix[CLASSES[label]][reading.answer] += 1
    per_class = {}
    for name in CLASSES:
        row = matrix[name]
        total = sum(row.values())
        right = row[name]
        not_sure = row[NOT_SURE]
        per_class[name] = {
            "right": right,
            "wrong": total - right - not_sure,
            "not_sure": not_sure,
            "total": total,
        }
    totals = {
        k: sum(c[k] for c in per_class.values()) for k in ("right", "wrong", "not_sure", "total")
    }
    return {"per_class": per_class, "total": totals, "confusion": matrix}


def format_report(summary: dict) -> str:
    lines = []
    for name, c in summary["per_class"].items():
        lines.append(
            f"{name:>5}: {c['right']} of {c['total']} right, "
            f"{c['wrong']} wrong, {c['not_sure']} not sure"
        )
    t = summary["total"]
    lines.append(
        f"  all: {t['right']} of {t['total']} right, {t['wrong']} wrong, {t['not_sure']} not sure"
    )
    lines.append("")
    lines.append("confusion (rows = truth, columns = answer):")
    lines.append(" " * 7 + "".join(f"{c:>9}" for c in COLUMNS))
    for name, row in summary["confusion"].items():
        lines.append(f"{name:>6} " + "".join(f"{row[c]:>9}" for c in COLUMNS))
    return "\n".join(lines)


def evaluate(
    out_dir: Path = DEFAULT_OUT, data: Path | None = None, threshold: float | None = None
) -> dict:
    out_dir = Path(out_dir)
    card = json.loads((out_dir / "model_card.json").read_text())
    net, card_threshold = load_model(out_dir)
    threshold = card_threshold if threshold is None else threshold
    if data is None:
        data = Path(card["data"]["folder"])
        _, samples = split_on_boards(list_samples(data), set(card["data"]["test_boards"]))
        scope = f"test boards {', '.join(card['data']['test_boards'])}"
    else:
        samples = list_samples(data)
        leaked = sorted({s.board for s in samples} & set(card["data"]["train_boards"]))
        if leaked:
            raise ValueError(f"boards {leaked} were used for training; scores on them mean nothing")
        scope = f"every photo in {data}"
    if not samples:
        raise ValueError("no photos to evaluate")
    images = torch.stack([load_image(s.path) for s in samples])
    readings = decide(led_model.predict_proba(net, images), threshold)
    summary = summarise([s.label for s in samples], readings)
    summary.update(
        {
            "scope": scope,
            "threshold": threshold,
            "synthetic": is_synthetic(data),
            "note": "SYNTHETIC data: a plumbing check, not a result."
            if is_synthetic(data)
            else "Real photos.",
        }
    )
    (out_dir / "eval.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Score the debug-LED reader.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--data", type=Path, help="score every photo here instead of the test boards"
    )
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--threads", type=int, default=led_model.DEFAULT_THREADS)
    args = parser.parse_args()
    led_model.limit_threads(args.threads)
    summary = evaluate(args.out, args.data, args.threshold)
    print(
        f"{summary['note']}  Scope: {summary['scope']}.  Not-sure threshold: {summary['threshold']}"
    )
    print(format_report(summary))


if __name__ == "__main__":
    main()
