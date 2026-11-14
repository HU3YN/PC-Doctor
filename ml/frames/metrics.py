"""Counting right and wrong answers, the same way for the model and the rule.

Counts come first ("caught 41 of 50 stutter windows"); precision and recall
are derived from them. A bare percentage hides how many examples it rests on.
"""

from __future__ import annotations

import numpy as np


def score(labels: np.ndarray, predicted: np.ndarray) -> dict:
    """Confusion counts plus precision and recall for "stutter" (label 1).

    * recall    = stutter windows caught / all stutter windows
    * precision = right "stutter" answers / all "stutter" answers
    Either is ``None`` when its denominator is zero (undefined, not 0 or 1).
    """
    labels = np.asarray(labels).astype(bool)
    predicted = np.asarray(predicted).astype(bool)
    tp = int((labels & predicted).sum())  # stutter, said stutter
    fn = int((labels & ~predicted).sum())  # stutter, said smooth (missed)
    fp = int((~labels & predicted).sum())  # smooth, said stutter (false alarm)
    tn = int((~labels & ~predicted).sum())  # smooth, said smooth
    return {
        "windows": int(labels.size),
        "stutter_windows": tp + fn,
        "smooth_windows": tn + fp,
        "true_positives": tp,
        "false_negatives": fn,
        "false_positives": fp,
        "true_negatives": tn,
        "caught": f"{tp} of {tp + fn} stutter windows",
        "false_alarms": f"{fp} of {tn + fp} smooth windows",
        "precision": round(tp / (tp + fp), 4) if tp + fp else None,
        "recall": round(tp / (tp + fn), 4) if tp + fn else None,
        "accuracy": round((tp + tn) / labels.size, 4) if labels.size else None,
    }


def describe(name: str, s: dict) -> str:
    """One readable line for a score."""

    def pct(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.3f}"

    return (
        f"{name:<8} caught {s['caught']}, false alarms on {s['false_alarms']}; "
        f"precision {pct(s['precision'])}, recall {pct(s['recall'])}"
    )
