"""Find the LED photos, split them by board, and load them as tensors.

Layout (one folder per board, one folder per class inside it)::

    data/<board_id>/<class>/*.jpg      class is one of CLASSES

The split is by board: every photo of one board goes to train or to test,
never both. Photos of the same board look alike (same layout, same LED
colour, same silkscreen), so a photo-level split would let the model pass the
test by remembering boards instead of reading LEDs.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch.utils.data import Dataset

# Order matters: the model's outputs follow it. "none" = no debug LED lit.
CLASSES: tuple[str, ...] = ("none", "cpu", "dram", "vga", "boot")

# The no-boot guide code each class would map to (workers/pcdoctor_analysis/noboot.py).
# Kept here for when the reader is wired in; it is not wired in today.
NOBOOT_CODES: dict[str, str | None] = {
    "none": None,
    "cpu": "led_cpu",
    "dram": "led_dram",
    "vga": "led_vga",
    "boot": "led_boot",
}

IMAGE_SIZE = 96  # pixels, square; photos are resized to this
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
SYNTHETIC_MARKER = "SYNTHETIC"  # synth.py writes this file at the data root


@dataclass(frozen=True)
class Sample:
    path: Path
    board: str
    label: int  # index into CLASSES

    @property
    def class_name(self) -> str:
        return CLASSES[self.label]


def is_synthetic(root: Path) -> bool:
    return (Path(root) / SYNTHETIC_MARKER).exists()


def list_samples(root: Path) -> list[Sample]:
    """Every image under ``root/<board>/<class>/``, sorted so the order is stable.

    An unknown class folder is an error, not something to skip: a typo such as
    ``dram2/`` would otherwise drop photos without anyone noticing.
    """
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"no data folder at {root}")
    samples: list[Sample] = []
    for board_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if board_dir.name.startswith("."):
            continue
        for class_dir in sorted(p for p in board_dir.iterdir() if p.is_dir()):
            if class_dir.name not in CLASSES:
                raise ValueError(
                    f"unknown class folder {class_dir} (expected one of {', '.join(CLASSES)})"
                )
            label = CLASSES.index(class_dir.name)
            for path in sorted(class_dir.iterdir()):
                if path.suffix.lower() in IMAGE_SUFFIXES:
                    samples.append(Sample(path, board_dir.name, label))
    return samples


def split_by_board(
    samples: list[Sample], test_fraction: float = 0.25, seed: int = 0
) -> tuple[list[Sample], list[Sample]]:
    """Split so no board is in both train and test. Needs at least two boards."""
    if not 0.0 < test_fraction < 1.0:
        raise ValueError("test_fraction must be between 0 and 1")
    boards = sorted({s.board for s in samples})
    if len(boards) < 2:
        raise ValueError(f"need photos of at least 2 boards to split by board, got {len(boards)}")
    rng = random.Random(seed)
    rng.shuffle(boards)
    n_test = min(len(boards) - 1, max(1, round(len(boards) * test_fraction)))
    test_boards = set(boards[:n_test])
    return split_on_boards(samples, test_boards)


def split_on_boards(
    samples: list[Sample], test_boards: set[str]
) -> tuple[list[Sample], list[Sample]]:
    """Train = boards not in ``test_boards``; test = boards in it."""
    train = [s for s in samples if s.board not in test_boards]
    test = [s for s in samples if s.board in test_boards]
    return train, test


def class_counts(samples: list[Sample]) -> dict[str, int]:
    counts = dict.fromkeys(CLASSES, 0)
    for s in samples:
        counts[s.class_name] += 1
    return counts


def load_image(path: Path, size: int = IMAGE_SIZE) -> torch.Tensor:
    """RGB image -> float tensor (3, size, size) in [0, 1]."""
    with Image.open(path) as img:
        img = img.convert("RGB").resize((size, size), Image.BILINEAR)
        array = np.asarray(img, dtype=np.float32) / 255.0
    return torch.from_numpy(array).permute(2, 0, 1).contiguous()


class LedPhotos(Dataset):
    """Images and labels. ``augment`` adds brightness/contrast jitter and a small shift.

    No flips or rotations: which LED is lit is told partly by its position in
    the row, and a mirrored photo would move it.
    """

    def __init__(self, samples: list[Sample], augment: bool = False, seed: int = 0):
        self.samples = samples
        self.augment = augment
        self.generator = torch.Generator().manual_seed(seed)
        self.images = [load_image(s.path) for s in samples]  # small data: load once

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, int]:
        image = self.images[index]
        if self.augment:
            image = self._jitter(image)
        return image, self.samples[index].label

    def _jitter(self, image: torch.Tensor) -> torch.Tensor:
        g = self.generator
        gain = 0.75 + 0.5 * torch.rand(1, generator=g).item()
        bias = -0.08 + 0.16 * torch.rand(1, generator=g).item()
        dx, dy = (int(v) for v in torch.randint(-4, 5, (2,), generator=g))
        image = torch.roll(image, shifts=(dy, dx), dims=(1, 2))
        return (image * gain + bias).clamp(0.0, 1.0)
