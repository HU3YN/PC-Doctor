"""Fuzz errortext.interpret (workers/pcdoctor_analysis/errortext.py).

Its input is text read off a photo by OCR. Through the photo link, a
stranger's photo reaches it without any sign-in (routers/inbox.py,
send_photo), so the text is untrusted. The contract:

* it never raises;
* it "never invents a code that is not in the text" (its own docstring);
* it finishes quickly even on long, repetitive text (no regex blow-up).
"""

from __future__ import annotations

import json
import re
import time

from hypothesis import given
from hypothesis import strategies as st
from pcdoctor_analysis.errortext import ErrorReading, interpret
from pcdoctor_analysis.stopcodes import STOP_CODES

from harness import tolerate

NAMES = sorted(entry.name for entry in STOP_CODES.values())

# Pieces of real blue-screen wording, glued together in random order with
# OCR-style damage between them.
PIECES = st.one_of(
    st.sampled_from(
        [
            "Your PC ran into a problem and needs to restart.",
            "Stop code:",
            "stop code",
            "STOPCODE;",
            "What failed:",
            "what failed nvlddmkm.sys",
            "0x",
            "0X ",
            "0x00000124",
            "0xOOOOO124",
            "0xC0000005",
            "0xFFFFFFFFFFFFFFFF",
            ".sys",
            "a.sys",
            "-_-.sys",
            "\n",
            " ",
            "_",
            "O",
            "0",
        ]
    ),
    st.sampled_from(NAMES),
    st.sampled_from(NAMES).map(lambda name: name.replace("_", " ").lower()),
    st.sampled_from(NAMES).map(lambda name: name[:-1]),
    st.text(max_size=20),
    st.from_regex(r"0[xX] ?[0-9A-Fa-fOo]{1,10}", fullmatch=True),
)
ocr_text = st.one_of(
    st.lists(PIECES, max_size=30).map(" ".join),
    st.lists(PIECES, max_size=30).map("".join),
    st.text(max_size=400),
)


def check_reading(text: str) -> ErrorReading | None:
    try:
        reading = interpret(text)
    except Exception as error:  # noqa: BLE001 - it must never raise
        tolerate(error)
        return None
    assert isinstance(reading, ErrorReading)
    assert all(code.code in STOP_CODES for code in reading.stop_codes)
    assert len({code.code for code in reading.stop_codes}) == len(reading.stop_codes)
    # An unknown code is only reported if a hex number is really in the text.
    for code in reading.unknown_codes:
        assert re.fullmatch(r"0x[0-9A-F]+", code), code
        assert re.search(r"0[xX]", text), "an unknown code was reported with no 0x in the text"
    # A driver name is only reported if it is really in the text.
    for driver in reading.drivers:
        assert driver.lower() in text.lower()
    assert len({d.lower() for d in reading.drivers}) == len(reading.drivers)
    # What the API stores for a photo (routers/inbox.py, send_photo).
    json.dumps(
        {
            "stop_codes": [entry.to_dict() for entry in reading.stop_codes],
            "unknown_codes": reading.unknown_codes,
            "drivers": reading.drivers,
            "is_blue_screen": reading.is_blue_screen,
        },
        allow_nan=False,
    )
    return reading


@given(ocr_text)
def test_interpret(text: str) -> None:
    check_reading(text)


@given(
    st.sampled_from(["0x" * 1, "stop code ", "a.sys ", "A_", "what failed: ", "0xO", "- ", "_"]),
    st.integers(1, 4000),
    st.text(max_size=10),
)
def test_interpret_is_fast_on_long_repetitive_text(piece: str, repeats: int, tail: str) -> None:
    # The API keeps at most 4000 characters of OCR text, but interpret() gets
    # the full text first, so test well past that.
    text = piece * repeats + tail
    started = time.perf_counter()
    check_reading(text)
    elapsed = time.perf_counter() - started
    assert elapsed < 5.0, f"{elapsed:.1f}s for {len(text)} characters"
