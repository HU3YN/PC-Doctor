"""Photo-reader evaluation: how often is the stop code read correctly off a photo?

    python eval/photo_eval.py                  score eval/photos/ against its labels.csv
    python eval/photo_eval.py path/to/folder   score another folder
    python eval/photo_eval.py --synthetic 40   plumbing check on generated images

Every photo goes through the SAME code the server runs on an upload:
pcdoctor_api.services.photo.read_text (clean-up + Tesseract OCR), then
pcdoctor_analysis.errortext.interpret (find the stop code in the messy text).
The codes found are compared with what you wrote in labels.csv.

labels.csv has four columns:

    file,stop_code,source,notes
    bsod-desk-01.jpg,0x124,LCD monitor,taken at an angle
    bios-post-02.jpg,,BIOS screen,no stop code on this screen

  * stop_code is hex (0x124). Leave it EMPTY when the photo shows no stop code -
    those photos measure how often a code is invented out of nothing.
  * source is free text describing the screen (LCD monitor, laptop, TV, ...).

Each photo ends up in exactly one group:

  read correctly   the label's code was found and nothing else
  read WRONGLY     a code was reported that is not the label's. Counted apart
                   from "not read" because a wrong code sends the technician
                   down the wrong path; no code only costs them a retype.
  not read         no code was found
  could not open   the reader refused the file (not an image, too large, ...)

and for photos labeled as having no code: "nothing reported" or "code INVENTED".

Results are printed as counts ("7 of 9"), never as a bare percentage: with a
handful of photos a percentage hides how little it is based on.

--synthetic draws blue screens with Pillow and scores those. It proves this
script and the reader are connected properly. It is NOT a read rate: drawn
images have none of what makes a real photo hard (glare, focus, a curved
screen, a shaking hand), so its numbers must never be quoted as a result.

Nothing here re-encodes, moves or uploads a photo. Files are only read.
The script exits non-zero only when it could not be run as asked (missing
folder, broken labels.csv, OCR not installed) - never because photos read badly.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pcdoctor_analysis.errortext import interpret
from pcdoctor_analysis.stopcodes import STOP_CODES, format_code

PHOTOS = Path(__file__).parent / "photos"
LABELS_NAME = "labels.csv"
COLUMNS = ("file", "stop_code", "source", "notes")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# Outcomes for a photo labeled WITH a stop code.
CORRECT = "read correctly"
WRONG = "read WRONGLY"
NOT_READ = "not read"
# Outcomes for a photo labeled as having NO stop code.
NOTHING = "nothing reported"
INVENTED = "code INVENTED"
# Either kind.
UNREADABLE = "could not open"
MISSING = "file missing"

SYNTHETIC_BANNER = (
    "!!! PLUMBING CHECK ONLY - NOT A READ RATE !!!\n"
    "These are drawn images, not photographs. They show that the script and the\n"
    "reader are wired together. They say nothing about how real photos read.\n"
    "Do not copy these numbers into a README, a results page or a commit message."
)


class UsageError(Exception):
    """The script cannot do what was asked. The message is shown and the exit code is 2."""


@dataclass(frozen=True)
class Label:
    file: str
    stop_code: int | None  # None = the photo shows no stop code
    source: str = ""
    notes: str = ""


@dataclass(frozen=True)
class Result:
    label: Label
    outcome: str
    found: tuple[int, ...] = ()
    detail: str = ""  # why a file could not be opened


# A reader turns the bytes of one photo into the set of stop codes found in it.
# The real one is server_reader(); tests pass a stub so no OCR engine is needed.
Reader = Callable[[bytes], set[int]]


# ------------------------------------------------------------------ labels


def parse_code(text: str) -> int | None:
    """'0x124' -> 0x124, '' -> None. Raises ValueError with a readable message otherwise."""
    text = text.strip()
    if not text:
        return None
    if not text.lower().startswith("0x"):
        raise ValueError(f"stop_code {text!r} must be hex starting with 0x (like 0x124)")
    try:
        code = int(text, 16)
    except ValueError:
        raise ValueError(f"stop_code {text!r} is not a hex number (like 0x124)") from None
    if code <= 0:
        raise ValueError(f"stop_code {text!r} must be greater than zero")
    return code


def parse_labels(path: Path) -> tuple[list[Label], list[str]]:
    """The usable rows, and one plain-English message for every row that is not usable.

    A bad row is reported and skipped rather than stopping the run: one typo
    should not hide the other photos. The caller decides whether problems are fatal.
    """
    labels: list[Label] = []
    problems: list[str] = []
    seen: dict[str, int] = {}
    # utf-8-sig: Excel on Windows puts an invisible marker at the start of a CSV.
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        header = [name.strip().lower() for name in (reader.fieldnames or [])]
        missing = [name for name in ("file", "stop_code") if name not in header]
        if missing:
            return [], [
                f"{path.name}: the first line must name the columns "
                f"{','.join(COLUMNS)} - missing: {', '.join(missing)}"
            ]
        reader.fieldnames = header
        for row in reader:
            line = reader.line_num
            file = (row.get("file") or "").strip()
            if not any((value or "").strip() for value in row.values() if isinstance(value, str)):
                continue  # a blank line
            if not file:
                problems.append(f"{path.name} line {line}: no file name")
                continue
            if Path(file).name != file:
                problems.append(
                    f"{path.name} line {line}: {file!r} must be a plain file name in this "
                    "folder, not a path"
                )
                continue
            if file.lower() in seen:
                problems.append(
                    f"{path.name} line {line}: {file!r} is already labeled on line "
                    f"{seen[file.lower()]}"
                )
                continue
            try:
                code = parse_code(row.get("stop_code") or "")
            except ValueError as error:
                problems.append(f"{path.name} line {line}: {error}")
                continue
            seen[file.lower()] = line
            labels.append(
                Label(
                    file=file,
                    stop_code=code,
                    source=(row.get("source") or "").strip(),
                    notes=(row.get("notes") or "").strip(),
                )
            )
    return labels, problems


# ------------------------------------------------------------------ scoring


def judge(expected: int | None, found: set[int]) -> str:
    """Which group one photo falls in, given its label and the codes the reader reported."""
    if expected is None:
        return INVENTED if found else NOTHING
    if not found:
        return NOT_READ
    # The right code next to an extra one still counts as wrong: the technician
    # is shown both and cannot tell which to trust.
    return CORRECT if found == {expected} else WRONG


def server_reader(data: bytes) -> set[int]:
    """Exactly what the server does with a photo (POST /api/photos in routers/intake.py):
    photo.read_text, then errortext.interpret; the codes it shows are the known
    stop codes plus any unknown hex codes. Nothing here re-implements a step.
    """
    from pcdoctor_api.services import photo

    reading = interpret(photo.read_text(data))
    found = {entry.code for entry in reading.stop_codes}
    # The dashboard also shows hex codes that are not in the table, so they count.
    found |= {int(code, 16) for code in reading.unknown_codes}
    return found


def evaluate(folder: Path, labels: list[Label], reader: Reader) -> list[Result]:
    from pcdoctor_api.services.photo import PhotoError

    results = []
    for label in labels:
        path = folder / label.file
        if not path.is_file():
            results.append(Result(label, MISSING))
            continue
        try:
            found = reader(path.read_bytes())
        except PhotoError as error:
            results.append(Result(label, UNREADABLE, detail=str(error)))
            continue
        results.append(Result(label, judge(label.stop_code, found), tuple(sorted(found))))
    return results


def unlabeled_photos(folder: Path, labels: list[Label]) -> list[str]:
    """Image files in the folder that labels.csv does not mention (they are not scored)."""
    known = {label.file.lower() for label in labels}
    return sorted(
        path.name
        for path in folder.iterdir()
        if path.is_file()
        and path.suffix.lower() in IMAGE_SUFFIXES
        and path.name.lower() not in known
    )


def count(results: list[Result], outcome: str) -> int:
    return sum(1 for result in results if result.outcome == outcome)


def summary_lines(results: list[Result]) -> list[str]:
    """The summary, every figure as 'N of M'."""
    scored = [r for r in results if r.outcome != MISSING]
    with_code = [r for r in scored if r.label.stop_code is not None]
    without = [r for r in scored if r.label.stop_code is None]
    lines = [f"Photos scored: {len(scored)} of {len(results)} labeled"]
    missing = count(results, MISSING)
    if missing:
        lines.append(f"  file missing (not scored): {missing} of {len(results)}")
    lines.append(f"Photos labeled with a stop code: {len(with_code)}")
    if with_code:
        for outcome in (CORRECT, WRONG, NOT_READ, UNREADABLE):
            lines.append(f"  {outcome + ':':<19}{count(with_code, outcome)} of {len(with_code)}")
    lines.append(f"Photos labeled as showing no stop code: {len(without)}")
    if without:
        for outcome in (NOTHING, INVENTED, UNREADABLE):
            lines.append(f"  {outcome + ':':<19}{count(without, outcome)} of {len(without)}")
    sources = sorted({r.label.source for r in with_code if r.label.source})
    if len(sources) > 1:
        lines.append("Read correctly, by source:")
        for source in sources:
            group = [r for r in with_code if r.label.source == source]
            lines.append(f"  {source}: {count(group, CORRECT)} of {len(group)}")
    if len(with_code) < 30:
        lines.append(
            f"Only {len(with_code)} photos with a stop code: too few to call this a read rate. "
            "Report the counts as they are."
        )
    return lines


def photo_line(result: Result) -> str:
    label = result.label
    expected = format_code(label.stop_code) if label.stop_code is not None else "no code"
    found = ", ".join(format_code(code) for code in result.found) or "nothing"
    line = f"{result.outcome:<17} {label.file}  label: {expected}  found: {found}"
    if label.source:
        line += f"  [{label.source}]"
    if result.detail:
        line += f"  ({result.detail})"
    return line


def report(results: list[Result], out=None) -> None:
    out = sys.stdout if out is None else out  # looked up now, so redirection works
    for result in results:
        print(photo_line(result), file=out)
    print(file=out)
    for line in summary_lines(results):
        print(line, file=out)


# ------------------------------------------------------------------ synthetic images

_FONTS = ("DejaVuSans.ttf", "LiberationSans-Regular.ttf", "FreeSans.ttf", "arial.ttf")
_DRIVERS = ("nvlddmkm.sys", "ntfs.sys", "storport.sys", "dxgkrnl.sys")


def _font(rng: random.Random, size: int):
    from PIL import ImageFont

    for name in rng.sample(_FONTS, len(_FONTS)):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _screen_lines(rng: random.Random, kind: str, code: int | None) -> list[str]:
    if kind == "name":  # Windows 10/11: the code is given by name
        lines = [
            "Your PC ran into a problem and needs to restart. We're just",
            "collecting some error info, and then we'll restart for you.",
            "",
            f"{rng.randrange(0, 101)}% complete",
            "",
            "If you call a support person, give them this info:",
            f"Stop code: {STOP_CODES[code].name}",
        ]
        if rng.random() < 0.4:
            lines.append(f"What failed: {rng.choice(_DRIVERS)}")
        return lines
    if kind == "hex":  # Windows 7 and older: the code is a number
        return [
            "A problem has been detected and Windows has been shut down",
            "to prevent damage to your computer.",
            "",
            "Technical information:",
            "",
            f"*** STOP: 0x{code:08X}",
        ]
    # A start-up screen with no stop code at all: the reader must report nothing.
    return rng.choice(
        (
            [
                "Reboot and Select proper Boot device",
                "or Insert Boot Media in selected Boot device",
            ],
            ["Preparing Automatic Repair", "Diagnosing your PC"],
            ["No bootable device found.", "Press any key to restart the machine."],
        )
    )


def synthetic_image(rng: random.Random, kind: str, code: int | None):
    """One drawn error screen, degraded a little the way a phone photo of a screen is."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

    width, height = 1600, 900
    blue = kind != "none"
    background = (0, rng.randrange(90, 130), rng.randrange(190, 230)) if blue else (8, 8, 12)
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    size = rng.randrange(26, 44)
    font = _font(rng, size)
    x, y = rng.randrange(90, 140), rng.randrange(120, 240)
    for line in _screen_lines(rng, kind, code):
        draw.text((x, y), line, fill=(255, 255, 255), font=font)
        y += int(size * 1.5)

    # Moire-like pattern: a phone sensor photographing a pixel grid shows faint stripes.
    if rng.random() < 0.6:
        stripes = Image.new("RGB", (width, height), (0, 0, 0))
        stripe_draw = ImageDraw.Draw(stripes)
        step = rng.randrange(3, 7)
        for x in range(0, width + height, step * 2):
            stripe_draw.line([(x, 0), (x - height // 3, height)], fill=(255, 255, 255), width=step)
        image = Image.blend(image, stripes, rng.uniform(0.03, 0.10))

    # The image stands for a photo cropped to the screen: whatever the skew and
    # rotation uncover is filled with the screen's own colour, not a black
    # bezel. (The reader currently returns nothing when a dark border frames
    # the screen - that is a reader problem for real photos to measure, not
    # something a plumbing check should hide behind.)
    # Perspective-like skew: pull the corners of the source rectangle in or out.
    jitter = rng.randrange(0, 50)
    corners = []
    for cx, cy in ((0, 0), (0, height), (width, height), (width, 0)):
        corners += [cx + rng.randint(-jitter, jitter), cy + rng.randint(-jitter, jitter)]
    image = image.transform(
        (width, height),
        Image.Transform.QUAD,
        corners,
        Image.Resampling.BICUBIC,
        fillcolor=background,
    )
    image = image.rotate(
        rng.uniform(-4, 4), resample=Image.Resampling.BICUBIC, expand=True, fillcolor=background
    )
    image = image.filter(ImageFilter.GaussianBlur(rng.uniform(0.0, 1.6)))
    return ImageEnhance.Brightness(image).enhance(rng.uniform(0.6, 1.3))


def make_synthetic(folder: Path, count_: int, seed: int = 0) -> list[Label]:
    """Write count_ drawn error screens and their labels.csv into folder."""
    rng = random.Random(seed)
    codes = sorted(STOP_CODES)
    labels = []
    for index in range(count_):
        # Mostly blue screens; about one in six has no code, to exercise "invented".
        kind = rng.choices(("name", "hex", "none"), weights=(3, 2, 1))[0]
        code = rng.choice(codes) if kind != "none" else None
        name = f"synthetic-{index:03d}.jpg"
        synthetic_image(rng, kind, code).save(folder / name, "JPEG", quality=rng.randrange(35, 92))
        labels.append(
            Label(
                file=name,
                stop_code=code,
                source=f"synthetic ({kind})",
                notes="drawn image - plumbing check only",
            )
        )
    with (folder / LABELS_NAME).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        for label in labels:
            code_text = format_code(label.stop_code) if label.stop_code is not None else ""
            writer.writerow([label.file, code_text, label.source, label.notes])
    return labels


# ------------------------------------------------------------------ command line


def _require_ocr() -> None:
    from pcdoctor_api.services import photo

    try:
        photo._engine()  # the same check the server makes, with its explanation
    except photo.OcrUnavailable as error:
        raise UsageError(
            f"OCR is unavailable, so nothing can be measured: {error}\n"
            "Install the Tesseract program (Linux: apt-get install tesseract-ocr; Windows: the "
            "UB-Mannheim installer) and 'pip install pytesseract pillow', then run this again."
        ) from None


def run_folder(folder: Path, reader: Reader, out=None) -> list[Result]:
    out = sys.stdout if out is None else out
    if not folder.is_dir():
        raise UsageError(f"{folder} is not a folder")
    labels_path = folder / LABELS_NAME
    if not labels_path.is_file():
        raise UsageError(
            f"{labels_path} not found. Copy labels.example.csv to {LABELS_NAME} and add one "
            "line per photo."
        )
    labels, problems = parse_labels(labels_path)
    if problems:
        raise UsageError(
            "labels.csv needs fixing before anything is scored:\n  " + "\n  ".join(problems)
        )
    if not labels:
        raise UsageError(f"{labels_path} has no photos listed")
    results = evaluate(folder, labels, reader)
    report(results, out)
    extra = unlabeled_photos(folder, labels)
    if extra:
        print(
            f"\nNot scored - {len(extra)} image(s) in the folder have no line in "
            f"{LABELS_NAME}: {', '.join(extra)}",
            file=out,
        )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Score the photo reader (the server's own OCR path) against labeled photos."
    )
    parser.add_argument(
        "folder",
        nargs="?",
        type=Path,
        default=PHOTOS,
        help="folder of photos with a labels.csv (default: eval/photos)",
    )
    parser.add_argument(
        "--synthetic",
        type=int,
        metavar="N",
        help="draw N error screens and score those instead - a plumbing check, not a read rate",
    )
    parser.add_argument("--seed", type=int, default=0, help="seed for --synthetic (default 0)")
    args = parser.parse_args(argv)

    try:
        if args.synthetic is not None and args.synthetic < 1:
            raise UsageError("--synthetic needs a number of images of 1 or more")
        _require_ocr()
        if args.synthetic is None:
            run_folder(args.folder, server_reader)
            return 0
        print(SYNTHETIC_BANNER + "\n")
        with tempfile.TemporaryDirectory(prefix="pcdoctor-photo-eval-") as tmp:
            make_synthetic(Path(tmp), args.synthetic, args.seed)
            run_folder(Path(tmp), server_reader)
        print("\n" + SYNTHETIC_BANNER)
        return 0
    except UsageError as error:
        print(f"photo_eval: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
