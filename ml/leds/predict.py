"""Say which debug LED is lit in a photo - or "not sure".

    python predict.py photo.jpg [more.jpg ...]
    python predict.py --threshold 0.9 photo.jpg

If the model's top softmax probability is below the threshold, the answer is
"not sure" instead of a guess. The default threshold is the one in the model
card (set at training time).

Not wired into the API: it should only be once it has been measured on real
photos (see README.md).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import torch

import model as led_model
from dataset import CLASSES, NOBOOT_CODES, load_image

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "out"
NOT_SURE = "not sure"
DEFAULT_THRESHOLD = 0.8


@dataclass(frozen=True)
class Reading:
    answer: str  # a class name, or NOT_SURE
    confidence: float  # the top softmax probability
    best_guess: str  # the top class even when the answer is NOT_SURE
    noboot_code: str | None  # e.g. "led_dram"; None for "none" and "not sure"


def decide(probs: torch.Tensor, threshold: float) -> list[Reading]:
    """Turn softmax rows into answers, refusing to guess below ``threshold``."""
    readings = []
    for row in probs:
        confidence, index = (float(v) for v in row.max(dim=0))
        best = CLASSES[int(index)]
        answer = best if confidence >= threshold else NOT_SURE
        readings.append(Reading(answer, round(confidence, 4), best, NOBOOT_CODES.get(answer)))
    return readings


def load_model(out_dir: Path = DEFAULT_OUT) -> tuple[torch.nn.Module, float]:
    """The trained model and the threshold from its card."""
    net, _ = led_model.load(Path(out_dir) / "leds.pt")
    card_path = Path(out_dir) / "model_card.json"
    threshold = DEFAULT_THRESHOLD
    if card_path.exists():
        threshold = json.loads(card_path.read_text()).get("not_sure_threshold", threshold)
    return net, threshold


def predict_paths(paths: list[Path], net: torch.nn.Module, threshold: float) -> list[Reading]:
    images = torch.stack([load_image(p) for p in paths])
    return decide(led_model.predict_proba(net, images), threshold)


def main() -> None:
    parser = argparse.ArgumentParser(description="Read a motherboard's debug LEDs from a photo.")
    parser.add_argument("photos", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="folder with leds.pt")
    parser.add_argument("--threshold", type=float, help="override the model card's threshold")
    parser.add_argument("--threads", type=int, default=led_model.DEFAULT_THREADS)
    args = parser.parse_args()
    led_model.limit_threads(args.threads)
    net, threshold = load_model(args.out)
    if args.threshold is not None:
        threshold = args.threshold
    for path, reading in zip(args.photos, predict_paths(args.photos, net, threshold), strict=True):
        print(json.dumps({"photo": str(path), **asdict(reading)}))


if __name__ == "__main__":
    main()
