"""Tests for eval/photo_eval.py.

Most tests use a stub reader, so they need no OCR engine. The end-to-end
synthetic test runs the real Tesseract path and is skipped when it is missing.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
from pcdoctor_api.services import photo

import photo_eval as pe

# ------------------------------------------------------------------ scoring


@pytest.mark.parametrize(
    ("expected", "found", "outcome"),
    [
        (0x124, {0x124}, pe.CORRECT),
        (0x124, {0xEF}, pe.WRONG),
        (0x124, {0x124, 0xEF}, pe.WRONG),  # the right code next to a wrong one is still wrong
        (0x124, set(), pe.NOT_READ),
        (None, set(), pe.NOTHING),
        (None, {0x124}, pe.INVENTED),
    ],
)
def test_judge(expected, found, outcome):
    assert pe.judge(expected, found) == outcome


def _folder(tmp_path: Path, rows: list[tuple[str, str]], files=None) -> Path:
    lines = ["file,stop_code,source,notes"] + [f"{name},{code},LCD monitor," for name, code in rows]
    (tmp_path / pe.LABELS_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")
    for name in files if files is not None else [name for name, _ in rows]:
        (tmp_path / name).write_bytes(name.encode())  # the stub reader keys on the bytes
    return tmp_path


# What the stub "reads" from each file: its bytes are its name.
_STUB = {
    b"right.jpg": {0x124},
    b"wrong.jpg": {0xEF},
    b"none.jpg": set(),
    b"blank.jpg": set(),
    b"invented.jpg": {0x7B},
}


def _stub_reader(data: bytes) -> set[int]:
    if data == b"broken.jpg":
        raise photo.PhotoError("That file is not a photo this can read (use JPG or PNG).")
    return set(_STUB[data])


def test_right_wrong_and_none_are_counted_separately(tmp_path):
    folder = _folder(
        tmp_path,
        [
            ("right.jpg", "0x124"),
            ("wrong.jpg", "0x124"),
            ("none.jpg", "0x124"),
            ("broken.jpg", "0x124"),
            ("blank.jpg", ""),
            ("invented.jpg", ""),
            ("gone.jpg", "0x124"),
        ],
        files=["right.jpg", "wrong.jpg", "none.jpg", "broken.jpg", "blank.jpg", "invented.jpg"],
    )
    out = io.StringIO()
    results = pe.run_folder(folder, _stub_reader, out)
    outcomes = {r.label.file: r.outcome for r in results}
    assert outcomes == {
        "right.jpg": pe.CORRECT,
        "wrong.jpg": pe.WRONG,
        "none.jpg": pe.NOT_READ,
        "broken.jpg": pe.UNREADABLE,
        "blank.jpg": pe.NOTHING,
        "invented.jpg": pe.INVENTED,
        "gone.jpg": pe.MISSING,
    }
    text = out.getvalue()
    assert "read correctly:    1 of 4" in text
    assert "read WRONGLY:      1 of 4" in text
    assert "not read:          1 of 4" in text
    assert "could not open:    1 of 4" in text
    assert "nothing reported:  1 of 2" in text
    assert "code INVENTED:     1 of 2" in text
    assert "file missing (not scored): 1 of 7" in text
    assert "Photos scored: 6 of 7 labeled" in text


def test_summary_never_gives_a_bare_percentage(tmp_path):
    folder = _folder(tmp_path, [("right.jpg", "0x124"), ("wrong.jpg", "0x124")])
    out = io.StringIO()
    pe.run_folder(folder, _stub_reader, out)
    text = out.getvalue()
    assert "%" not in text
    summary = text.split("\n\n", 1)[1]
    # Every figure in an outcome line is "N of M".
    for line in summary.splitlines():
        if line.startswith("  ") and ":" in line:
            assert re.search(r"\d+ of \d+$", line), line
    assert "too few to call this a read rate" in text


def test_summary_counts_by_source():
    labels = [
        pe.Label("a.jpg", 0x124, "LCD monitor"),
        pe.Label("b.jpg", 0x124, "laptop"),
        pe.Label("c.jpg", 0x124, "laptop"),
    ]
    results = [
        pe.Result(labels[0], pe.CORRECT, (0x124,)),
        pe.Result(labels[1], pe.CORRECT, (0x124,)),
        pe.Result(labels[2], pe.WRONG, (0xEF,)),
    ]
    lines = pe.summary_lines(results)
    assert "  LCD monitor: 1 of 1" in lines
    assert "  laptop: 1 of 2" in lines


def test_unlabeled_photos_are_listed_not_scored(tmp_path):
    folder = _folder(tmp_path, [("right.jpg", "0x124")])
    (folder / "extra.png").write_bytes(b"x")
    out = io.StringIO()
    results = pe.run_folder(folder, _stub_reader, out)
    assert len(results) == 1
    assert "extra.png" in out.getvalue()


# ------------------------------------------------------------------ labels


def test_parse_labels_reports_bad_rows(tmp_path):
    path = tmp_path / pe.LABELS_NAME
    path.write_text(
        "﻿file,stop_code,source,notes\n"
        "a.jpg,0x124,LCD,\n"
        "b.jpg,124,LCD,\n"
        "sub/c.jpg,0x124,LCD,\n"
        "A.jpg,0xEF,LCD,\n"
        "\n"
        "d.jpg,,BIOS screen,no code\n",
        encoding="utf-8",
    )
    labels, problems = pe.parse_labels(path)
    assert [(label.file, label.stop_code) for label in labels] == [
        ("a.jpg", 0x124),
        ("d.jpg", None),
    ]
    assert len(problems) == 3
    assert any("must be hex" in p for p in problems)
    assert any("plain file name" in p for p in problems)
    assert any("already labeled" in p for p in problems)


def test_example_labels_parse():
    labels, problems = pe.parse_labels(pe.PHOTOS / "labels.example.csv")
    assert problems == []
    assert len(labels) == 4
    assert labels[-1].stop_code is None


def test_broken_labels_stop_the_run(tmp_path):
    (tmp_path / pe.LABELS_NAME).write_text("file,stop_code\nx.jpg,zzz\n", encoding="utf-8")
    with pytest.raises(pe.UsageError, match="needs fixing"):
        pe.run_folder(tmp_path, _stub_reader, io.StringIO())


def test_missing_labels_is_a_usage_error(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(pe, "_require_ocr", lambda: None)
    assert pe.main([str(tmp_path)]) == 2
    assert "labels.csv" in capsys.readouterr().err


# ------------------------------------------------------------------ the server's own code


def test_server_reader_calls_the_servers_photo_reader(monkeypatch):
    seen = []

    def fake_read_text(data: bytes) -> str:
        seen.append(data)
        return (
            "Your PC ran into a problem\nStop code: WHEA_UNCORRECTABLE_ERROR\n*** STOP: 0x000000EF"
        )

    monkeypatch.setattr(photo, "read_text", fake_read_text)
    found = pe.server_reader(b"photo bytes")
    assert seen == [b"photo bytes"]
    assert found == {0x124, 0xEF}


def test_server_reader_keeps_unknown_hex_codes(monkeypatch):
    # The dashboard shows a hex code that is not in the table, so it counts as reported.
    monkeypatch.setattr(photo, "read_text", lambda data: "Stop: 0x0000ABCD")
    assert pe.server_reader(b"x") == {0xABCD}


def test_main_uses_server_reader(tmp_path, monkeypatch, capsys):
    folder = _folder(tmp_path, [("right.jpg", "0x124")])
    monkeypatch.setattr(pe, "_require_ocr", lambda: None)
    monkeypatch.setattr(photo, "read_text", lambda data: "Stop code: WHEA_UNCORRECTABLE_ERROR")
    assert pe.main([str(folder)]) == 0
    assert "read correctly:    1 of 1" in capsys.readouterr().out


def test_photo_error_from_the_server_is_could_not_open(tmp_path, monkeypatch):
    folder = _folder(tmp_path, [("right.jpg", "0x124")])

    def refuse(data: bytes) -> str:
        raise photo.PhotoError("That file is not a photo this can read (use JPG or PNG).")

    monkeypatch.setattr(photo, "read_text", refuse)
    results = pe.run_folder(folder, pe.server_reader, io.StringIO())
    assert results[0].outcome == pe.UNREADABLE


def test_no_ocr_is_a_usage_error(monkeypatch, capsys):
    def unavailable():
        raise photo.OcrUnavailable("Tesseract is not installed")

    monkeypatch.setattr(photo, "_engine", unavailable)
    assert pe.main(["--synthetic", "1"]) == 2
    assert "OCR is unavailable" in capsys.readouterr().err


# ------------------------------------------------------------------ synthetic


def test_make_synthetic_writes_images_and_labels(tmp_path):
    pytest.importorskip("PIL")
    labels = pe.make_synthetic(tmp_path, 6, seed=3)
    parsed, problems = pe.parse_labels(tmp_path / pe.LABELS_NAME)
    assert problems == []
    assert parsed == labels
    assert all((tmp_path / label.file).is_file() for label in labels)
    assert all(label.source.startswith("synthetic") for label in labels)


def test_synthetic_end_to_end_through_tesseract(capsys):
    if not photo.available():
        pytest.skip("Tesseract OCR is not installed")
    assert pe.main(["--synthetic", "6", "--seed", "1"]) == 0
    out = capsys.readouterr().out
    assert out.count("PLUMBING CHECK ONLY - NOT A READ RATE") == 2
    assert "Photos scored: 6 of 6 labeled" in out
    # The plumbing is connected only if at least one drawn code comes back right.
    match = re.search(r"read correctly:\s+(\d+) of (\d+)", out)
    assert match and int(match.group(1)) >= 1
