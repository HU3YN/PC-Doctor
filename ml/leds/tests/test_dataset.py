from pathlib import Path

import pytest
import torch
from PIL import Image

from dataset import (
    CLASSES,
    IMAGE_SIZE,
    NOBOOT_CODES,
    LedPhotos,
    Sample,
    class_counts,
    is_synthetic,
    list_samples,
    split_by_board,
)


def _photo(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 30), (10, 80, 20)).save(path)


def _tree(root: Path, boards: int, per_class: int = 2) -> None:
    for b in range(boards):
        for c in CLASSES:
            for k in range(per_class):
                _photo(root / f"board{b}" / c / f"{k}.jpg")


def test_classes_match_the_noboot_guide():
    assert CLASSES == ("none", "cpu", "dram", "vga", "boot")
    assert NOBOOT_CODES == {
        "none": None,
        "cpu": "led_cpu",
        "dram": "led_dram",
        "vga": "led_vga",
        "boot": "led_boot",
    }


def test_list_samples_reads_board_and_class_from_folders(tmp_path):
    _tree(tmp_path, boards=2)
    (tmp_path / "board0" / "cpu" / "notes.txt").write_text("not a photo")
    samples = list_samples(tmp_path)
    assert len(samples) == 2 * len(CLASSES) * 2
    assert {s.board for s in samples} == {"board0", "board1"}
    assert class_counts(samples) == dict.fromkeys(CLASSES, 4)
    assert samples == list_samples(tmp_path)  # stable order


def test_unknown_class_folder_is_an_error(tmp_path):
    _photo(tmp_path / "board0" / "dram2" / "a.jpg")
    with pytest.raises(ValueError, match="unknown class folder"):
        list_samples(tmp_path)


def test_missing_data_folder_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        list_samples(tmp_path / "nope")


def _samples(boards: int, per_board: int = 5) -> list[Sample]:
    return [
        Sample(Path(f"{b}-{k}.jpg"), f"b{b}", k % len(CLASSES))
        for b in range(boards)
        for k in range(per_board)
    ]


@pytest.mark.parametrize("boards", [2, 3, 8, 21])
def test_split_never_puts_a_board_in_both_halves(boards):
    samples = _samples(boards)
    train, test = split_by_board(samples, test_fraction=0.25, seed=1)
    train_boards, test_boards = {s.board for s in train}, {s.board for s in test}
    assert train_boards and test_boards
    assert not train_boards & test_boards
    assert len(train) + len(test) == len(samples)


def test_split_is_seeded():
    samples = _samples(10)
    assert split_by_board(samples, seed=3) == split_by_board(samples, seed=3)
    tests = {frozenset(s.board for s in split_by_board(samples, seed=s)[1]) for s in range(10)}
    assert len(tests) > 1  # different seeds pick different boards


def test_split_needs_two_boards():
    with pytest.raises(ValueError, match="at least 2 boards"):
        split_by_board(_samples(1))


def test_photos_load_as_fixed_size_tensors(tmp_path):
    _tree(tmp_path, boards=1, per_class=1)
    data = LedPhotos(list_samples(tmp_path), augment=True, seed=0)
    image, label = data[0]
    assert image.shape == (3, IMAGE_SIZE, IMAGE_SIZE)
    assert image.dtype == torch.float32
    assert float(image.min()) >= 0.0 and float(image.max()) <= 1.0
    assert label == CLASSES.index("boot")  # folders sort: boot, cpu, dram, none, vga
    assert not is_synthetic(tmp_path)
