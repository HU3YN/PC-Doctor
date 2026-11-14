"""Draw fake debug-LED photos - for testing the PLUMBING only.

    python synth.py                         # data-synth/ with 8 boards
    python synth.py --boards 4 --per-class 6 --out /tmp/leds

Each "board" is a random style seed: board colour, where the LED row sits,
horizontal or vertical row, LED colour (amber, red or white), label text
size. Every photo of a board then gets its own position, scale, blur, noise
and brightness. One LED is lit per class folder (none for ``none``).

A model trained on these pictures has learnt to read these pictures. Its
scores say the code runs end to end; they say nothing about real boards.
synth.py writes a ``SYNTHETIC`` marker file so train.py labels its model card.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from dataset import CLASSES, SYNTHETIC_MARKER

HERE = Path(__file__).resolve().parent
LED_NAMES = ("CPU", "DRAM", "VGA", "BOOT")  # order on the board, same as CLASSES[1:]
LIT_COLOURS = {"amber": (255, 170, 30), "red": (255, 40, 30), "white": (255, 250, 235)}
PHOTO_SIZE = (160, 120)


def board_style(board_seed: int) -> dict:
    rng = random.Random(board_seed)
    base = rng.choice([(20, 60, 30), (25, 25, 30), (40, 40, 45), (15, 30, 70), (60, 20, 20)])
    return {
        "board": tuple(min(255, max(0, c + rng.randint(-12, 12))) for c in base),
        "vertical": rng.random() < 0.4,
        "lit": rng.choice(list(LIT_COLOURS)),
        "spacing": rng.uniform(16, 24),
        "led_size": rng.uniform(3.0, 5.0),
        "label_side": rng.choice([-1, 1]),
        "traces": rng.randint(3, 10),
        "trace_seed": rng.randrange(1 << 30),
    }


def draw_photo(style: dict, lit_index: int | None, rng: random.Random) -> Image.Image:
    """One photo. ``lit_index`` is 0..3 (CPU, DRAM, VGA, BOOT) or None."""
    w, h = PHOTO_SIZE
    img = Image.new("RGB", (w, h), style["board"])
    draw = ImageDraw.Draw(img)

    # Board clutter: traces and a couple of chips, fixed per board.
    trace_rng = random.Random(style["trace_seed"])
    for _ in range(style["traces"]):
        y = trace_rng.randint(0, h)
        x0 = trace_rng.randint(0, w)
        shade = tuple(min(255, c + 25) for c in style["board"])
        draw.line([(x0, y), (x0 + trace_rng.randint(20, 90), y)], fill=shade, width=1)
    for _ in range(2):
        x, y = trace_rng.randint(0, w - 30), trace_rng.randint(0, h - 20)
        draw.rectangle([x, y, x + 26, y + 16], fill=(18, 18, 20))

    # The LED row, placed and scaled per photo.
    scale = rng.uniform(0.8, 1.25)
    spacing = style["spacing"] * scale
    size = style["led_size"] * scale
    span = spacing * 3
    if style["vertical"]:
        cx = rng.uniform(30, w - 30)
        cy0 = rng.uniform(12, max(13, h - 12 - span))
        centres = [(cx, cy0 + i * spacing) for i in range(4)]
    else:
        cx0 = rng.uniform(15, max(16, w - 15 - span))
        cy = rng.uniform(20, h - 20)
        centres = [(cx0 + i * spacing, cy) for i in range(4)]

    glow = Image.new("RGB", (w, h), (0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    lit_rgb = LIT_COLOURS[style["lit"]]
    for i, ((x, y), name) in enumerate(zip(centres, LED_NAMES, strict=True)):
        box = [x - size, y - size * 0.7, x + size, y + size * 0.7]
        if i == lit_index:
            draw.rectangle(box, fill=lit_rgb)
            r = size * 3
            glow_draw.ellipse([x - r, y - r, x + r, y + r], fill=lit_rgb)
        else:
            draw.rectangle(box, fill=(200, 195, 170), outline=(90, 90, 80))
        if style["vertical"]:
            tx, ty = (
                x + style["label_side"] * (size + 4) - (22 if style["label_side"] < 0 else 0),
                y - 5,
            )
        else:
            tx, ty = (
                x - 9,
                y + style["label_side"] * (size + 4) - (10 if style["label_side"] < 0 else 0),
            )
        draw.text((tx, ty), name, fill=(235, 235, 235))

    if lit_index is not None:
        glow = glow.filter(ImageFilter.GaussianBlur(size * 1.5))
        img = Image.fromarray(
            np.clip(
                np.asarray(img, np.float32) + 0.8 * np.asarray(glow, np.float32), 0, 255
            ).astype(np.uint8)
        )

    img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.0, 1.2)))
    array = np.asarray(img, np.float32) * rng.uniform(0.6, 1.3)
    nprng = np.random.default_rng(rng.randrange(1 << 30))
    array += nprng.normal(0.0, rng.uniform(2.0, 10.0), array.shape)
    return Image.fromarray(np.clip(array, 0, 255).astype(np.uint8))


def generate(out: Path, boards: int = 8, per_class: int = 30, seed: int = 0) -> int:
    """Write ``out/<board>/<class>/NNN.jpg``. Returns the number of images written."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / SYNTHETIC_MARKER).write_text(
        "Made by synth.py. Synthetic pictures, for plumbing checks only.\n"
    )
    rng = random.Random(seed)
    written = 0
    for b in range(boards):
        style = board_style(rng.randrange(1 << 30))
        for label, name in enumerate(CLASSES):
            folder = out / f"synth-{b:02d}" / name
            folder.mkdir(parents=True, exist_ok=True)
            lit_index = None if name == "none" else label - 1
            for k in range(per_class):
                draw_photo(style, lit_index, rng).save(folder / f"{k:03d}.jpg", quality=90)
                written += 1
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=HERE / "data-synth")
    parser.add_argument("--boards", type=int, default=8)
    parser.add_argument("--per-class", type=int, default=30)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    n = generate(args.out, args.boards, args.per_class, args.seed)
    print(f"wrote {n} synthetic images ({args.boards} boards) to {args.out}")


if __name__ == "__main__":
    main()
