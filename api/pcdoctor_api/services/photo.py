"""Read the text off a photo of an error screen (OCR).

Uses Tesseract, an open-source OCR engine built on a neural network. It is
an optional extra: without it everything else works and this feature says
plainly that it is unavailable.

The photo is processed in memory and thrown away. It is never written to
disk or to the database - a photo of someone's screen is not ours to keep.
"""

from __future__ import annotations

import io
import shutil
from pathlib import Path

MAX_PIXELS = 40_000_000  # refuse absurd images before decoding them fully
MAX_SIDE = 2400  # phone photos are downscaled to this; plenty for screen text
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
    return pytesseract, Image


def available() -> bool:
    try:
        _engine()
    except OcrUnavailable:
        return False
    return True


def read_text(data: bytes) -> str:
    """The text in the image. Raises PhotoError for something that is not a usable image."""
    pytesseract, Image = _engine()
    from PIL import ImageOps, UnidentifiedImageError

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
        raise PhotoError("That file is not a photo this can read (use JPG or PNG).") from None

    image = ImageOps.exif_transpose(image)  # phones store rotation separately
    image = image.convert("L")
    if max(image.size) > MAX_SIDE:
        image.thumbnail((MAX_SIDE, MAX_SIDE))
    elif max(image.size) < 1000:
        image = image.resize((image.width * 2, image.height * 2))  # small text reads badly
    image = ImageOps.autocontrast(image)
    # OCR expects dark text on a light page; error screens are the reverse.
    histogram = image.histogram()
    dark = sum(histogram[:128])
    if dark > sum(histogram[128:]):
        image = ImageOps.invert(image)
    try:
        return pytesseract.image_to_string(image, config="--psm 6", timeout=30).strip()
    except RuntimeError:
        raise PhotoError("Reading the photo took too long. Try a closer, sharper photo.") from None


def to_jpeg(data: bytes) -> bytes:
    """Re-encode an upload as a plain JPEG.

    Decoding and re-encoding proves it really is an image, shrinks phone
    photos, and drops everything that is not pixels - including the GPS
    position and phone model that cameras hide inside the file.
    """
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError as error:
        raise OcrUnavailable("Photo support is not installed on this server.") from error
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
        raise PhotoError("That file is not a photo this can read (use JPG or PNG).") from None
    image = ImageOps.exif_transpose(image).convert("RGB")
    if max(image.size) > MAX_SIDE:
        image.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=85)
    return out.getvalue()
