import numpy as np
from PIL import Image

from dataset import CLASSES, is_synthetic, list_samples
from synth import PHOTO_SIZE, generate


def test_generate_writes_the_class_folder_layout(tmp_path):
    n = generate(tmp_path, boards=3, per_class=2, seed=0)
    assert n == 3 * len(CLASSES) * 2
    assert is_synthetic(tmp_path)
    samples = list_samples(tmp_path)
    assert len(samples) == n
    assert len({s.board for s in samples}) == 3
    with Image.open(samples[0].path) as img:
        assert img.size == PHOTO_SIZE


def test_generate_is_seeded(tmp_path):
    generate(tmp_path / "a", boards=2, per_class=1, seed=5)
    generate(tmp_path / "b", boards=2, per_class=1, seed=5)
    a = sorted(p.relative_to(tmp_path / "a") for p in (tmp_path / "a").rglob("*.jpg"))
    for rel in a:
        assert (tmp_path / "a" / rel).read_bytes() == (tmp_path / "b" / rel).read_bytes()


def test_a_lit_led_makes_the_photo_brighter(tmp_path):
    # Same board style and same per-photo randomness, only the lit LED differs.
    import random

    from synth import board_style, draw_photo

    style = board_style(42)
    dark = draw_photo(style, None, random.Random(7))
    lit = draw_photo(style, 2, random.Random(7))
    assert np.asarray(lit.convert("L")).sum() > np.asarray(dark.convert("L")).sum()
