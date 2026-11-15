"""Read the text off a photo of an error screen (OCR).

Uses Tesseract, an open-source OCR engine built on a neural network. It is
an optional extra: without it everything else works and this feature says
plainly that it is unavailable.

The photo is processed in memory and thrown away. It is never written to
disk or to the database - a photo of someone's screen is not ours to keep.
"""

from __future__ import annotations

import io
import os
import shutil
import time
from pathlib import Path

MAX_PIXELS = 40_000_000  # refuse absurd images before decoding them fully
MAX_SIDE = 2400  # phone photos are downscaled to this; plenty for screen text
OCR_SECONDS = 40  # for all the attempts on one photo together
ENOUGH_LETTERS = 40  # an error screen read this well needs no second attempt
WINDOWS_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


class PhotoError(ValueError):
    """The photo cannot be read. The message is safe to show to the user."""


class OcrUnavailable(RuntimeError):
    """Tesseract or its Python packages are not installed on this server."""


def _engine():
    try:
        import pytesseract
        from PIL import Image
    except ImportError as error:
        raise OcrUnavailable(
            "Photo reading is not installed on this server (pip install 'pcdoctor-api[photo]')."
        ) from error
    command = shutil.which("tesseract")
    if not command and WINDOWS_TESSERACT.is_file():
        command = str(WINDOWS_TESSERACT)
    if not command:
        raise OcrUnavailable(
            "Photo reading needs the Tesseract OCR program, which is not installed on this "
            "server. The Docker version includes it."
        )
    pytesseract.pytesseract.tesseract_cmd = command
    # One thread per Tesseract run. Its own threading gains little on a page
    # this size and becomes many times slower when the machine is busy.
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    return pytesseract, Image


def available() -> bool:
    try:
        _engine()
    except OcrUnavailable:
        return False
    return True


ALLOWED_FORMATS = ("JPEG", "PNG", "WEBP")


def open_photo(data: bytes):
    """Decode an upload as JPEG, PNG or WebP only - not every format Pillow
    knows (each one is more parser code facing a stranger's file) - and refuse
    images too large to decode safely instead of only warning about them."""
    import warnings

    from PIL import Image, UnidentifiedImageError

    try:
        with warnings.catch_warnings():
            # Pillow's own bomb check (its default limit) stays on, as an error.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data), formats=ALLOWED_FORMATS)
            # Our own, lower limit, checked from the header before any pixel
            # is decoded. (Not by changing Image.MAX_IMAGE_PIXELS: that is one
            # setting for the whole process.)
            width, height = image.size
            if width * height > MAX_PIXELS:
                raise PhotoError("That photo is too large. Use one under 40 megapixels.")
            image.load()
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise PhotoError("That file is not a photo this can read (use JPG or PNG).") from None
    return image


def read_text(data: bytes) -> str:
    """The text in the image. Raises PhotoError for something that is not a usable image.

    A phone photo of a screen is rarely just the screen: there is a bezel, a
    desk, and the photo is a little tilted. Tesseract reads none of that well,
    so a few prepared versions of the photo are tried and the one that gives
    the most letters and digits wins.
    """
    pytesseract, Image = _engine()
    from PIL import ImageOps

    image = open_photo(data)

    image = ImageOps.exif_transpose(image)  # phones store rotation separately
    image = image.convert("L")
    if max(image.size) > MAX_SIDE:
        image.thumbnail((MAX_SIDE, MAX_SIDE))
    elif max(image.size) < 1000:
        image = image.resize((image.width * 2, image.height * 2))  # small text reads badly

    screen = crop_to_screen(image)
    attempts = [  # (picture, Tesseract page mode), most likely to work first
        (dark_text_on_light(screen), "6"),  # 6 = one block of text
        (black_and_white(dark_text_on_light(screen)), "6"),
        (dark_text_on_light(screen), "11"),  # 11 = scattered text
    ]
    if screen is not image:  # the whole photo too, in case the crop was wrong
        attempts.append((dark_text_on_light(image), "6"))
    best, deadline = "", time.monotonic() + OCR_SECONDS
    for picture, mode in attempts:
        left = deadline - time.monotonic()
        if left <= 1:
            break
        try:
            text = pytesseract.image_to_string(
                picture, config=f"--psm {mode}", timeout=left
            ).strip()
        except RuntimeError:  # this attempt ran out of time
            break
        if _letters(text) > _letters(best):
            best = text
        if _letters(best) >= ENOUGH_LETTERS:
            break  # a screenful of text: the other attempts will not beat it
    if not best and time.monotonic() >= deadline - 1:
        raise PhotoError("Reading the photo took too long. Try a closer, sharper photo.")
    return best


def _letters(text: str) -> int:
    return sum(char.isalnum() for char in text)


def otsu_threshold(histogram: list[int]) -> int:
    """The grey level that best splits the picture into dark and light (Otsu's method)."""
    total = sum(histogram)
    weighted_total = sum(level * count for level, count in enumerate(histogram))
    best_spread, threshold = -1.0, 127
    dark_count = dark_weighted = 0
    for level in range(256):
        dark_count += histogram[level]
        dark_weighted += level * histogram[level]
        light_count = total - dark_count
        if dark_count == 0 or light_count == 0:
            continue
        dark_mean = dark_weighted / dark_count
        light_mean = (weighted_total - dark_weighted) / light_count
        spread = dark_count * light_count * (dark_mean - light_mean) ** 2
        if spread > best_spread:
            best_spread, threshold = spread, level
    return threshold


def crop_to_screen(image):
    """Cut a photo down to the lit screen in it, and paint any dark corners
    left by a tilted photo in the screen's own colour."""
    threshold = otsu_threshold(image.histogram())
    box = image.point(lambda p: 255 if p > threshold else 0).getbbox()
    if not box or (box[2] - box[0]) * (box[3] - box[1]) < 0.15 * image.width * image.height:
        return image  # nothing that looks like a lit screen: leave the photo alone
    screen = image.crop(box)
    light = screen.histogram()[threshold + 1 :]
    if sum(light) < 0.5 * screen.width * screen.height:
        # Mostly dark inside the box: the light part is the text on a dark
        # screen, not a lit screen in a dark room. Nothing to cut away.
        return image
    half, seen, fill = sum(light) / 2, 0, 255
    for offset, count in enumerate(light):  # the median of the lit part
        seen += count
        if seen >= half:
            fill = threshold + 1 + offset
            break
    return screen.point(lambda p: fill if p <= threshold else p)


def dark_text_on_light(image):
    """Stretch the contrast and make the text dark: OCR expects a printed page,
    and error screens are light text on a dark background."""
    from PIL import ImageOps

    image = ImageOps.autocontrast(image)
    histogram = image.histogram()
    if sum(histogram[:128]) > sum(histogram[128:]):
        image = ImageOps.invert(image)
    return image


def black_and_white(image):
    """Only black and white, split at the Otsu level, with the (smaller) text black."""
    from PIL import ImageOps

    threshold = otsu_threshold(image.histogram())
    image = image.point(lambda p: 255 if p > threshold else 0)
    histogram = image.histogram()
    if histogram[0] > histogram[255]:
        image = ImageOps.invert(image)
    return image


def to_jpeg(data: bytes) -> bytes:
    """Re-encode an upload as a plain JPEG.

    Decoding and re-encoding proves it really is an image, shrinks phone
    photos, and drops everything that is not pixels - including the GPS
    position and phone model that cameras hide inside the file.
    """
    try:
        from PIL import ImageOps
    except ImportError as error:
        raise OcrUnavailable("Photo support is not installed on this server.") from error
    image = open_photo(data)
    image = ImageOps.exif_transpose(image).convert("RGB")
    if max(image.size) > MAX_SIDE:
        image.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=85)
    return out.getvalue()
