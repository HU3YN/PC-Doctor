"""Make sense of text read off a photo of an error screen.

The text comes from OCR, so it is messy: "0" and "O" swap, underscores go
missing, lines break in odd places. This finds what can be found - stop
codes by number or by name, and the driver a blue screen blames - and never
invents a code that is not in the text.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from .stopcodes import STOP_CODES, StopCode, format_code

_HEX = re.compile(r"\b0[xX]\s?([0-9A-Fa-fOo]{2,8})\b")
_STOP_LINE = re.compile(r"stop\s*code\s*[:;.]?\s*([A-Za-z0-9_ \-]{6,60})", re.IGNORECASE)
_FAILED = re.compile(
    r"what\s*failed\s*[:;.]?\s*([A-Za-z0-9_\-]{2,40}\.(?:sys|dll|exe))", re.IGNORECASE
)
_DRIVER = re.compile(r"\b([A-Za-z0-9_\-]{2,40}\.sys)\b", re.IGNORECASE)

_NAMES = {entry.name: entry for entry in STOP_CODES.values()}


@dataclass
class ErrorReading:
    stop_codes: list[StopCode] = field(default_factory=list)
    unknown_codes: list[str] = field(default_factory=list)  # hex codes not in the table
    drivers: list[str] = field(default_factory=list)  # e.g. nvlddmkm.sys
    is_blue_screen: bool = False


def _squash(text: str) -> str:
    """Upper-case with every run of non-letters/digits as one underscore."""
    return re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_")


def interpret(text: str) -> ErrorReading:
    reading = ErrorReading()
    if not text or not text.strip():
        return reading
    lowered = text.lower()
    reading.is_blue_screen = any(
        phrase in lowered
        for phrase in (
            "ran into a problem",
            "stop code",
            "needs to restart",
            "collecting some error",
        )
    )
    found: dict[int, StopCode] = {}

    # 1. By name: "Stop code: CRITICAL PROCESS DIED" (underscores often lost).
    squashed = _squash(text)
    for name, entry in _NAMES.items():
        if len(name) >= 10 and name in squashed:
            found.setdefault(entry.code, entry)
    # A longer name contains a shorter one (..._NOT_HANDLED_M): keep the longest.
    for entry in list(found.values()):
        if any(o.name != entry.name and entry.name in o.name for o in found.values()):
            del found[entry.code]
    if not found:
        match = _STOP_LINE.search(text)
        if match:
            guess = _squash(match.group(1))
            close = difflib.get_close_matches(guess, list(_NAMES), n=1, cutoff=0.82)
            if close:
                found[_NAMES[close[0]].code] = _NAMES[close[0]]

    # 2. By number: 0x00000124. OCR reads 0 as O, so both are accepted.
    for match in _HEX.finditer(text):
        digits = match.group(1).upper().replace("O", "0")
        code = int(digits, 16)
        if code == 0:
            continue
        if code in STOP_CODES:
            found.setdefault(code, STOP_CODES[code])
        elif (
            len(digits) >= 3
            and format_code(code) not in reading.unknown_codes
            # Blue screens print four long parameter values too; only a short
            # number is plausibly the stop code itself.
            and (code <= 0xFFFFF or digits.startswith("C0000"))
        ):
            reading.unknown_codes.append(format_code(code))

    failed = _FAILED.search(text)
    names = [failed.group(1)] if failed else []
    names += [m.group(1) for m in _DRIVER.finditer(text)]
    for name in names:
        if name.lower() not in (d.lower() for d in reading.drivers):
            reading.drivers.append(name)

    reading.stop_codes = sorted(found.values(), key=lambda e: (not e.meaning, e.code))
    if reading.stop_codes:
        reading.unknown_codes = []  # the parameters of a known crash are noise
    return reading
