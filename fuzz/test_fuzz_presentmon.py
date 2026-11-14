"""Fuzz the PresentMon CSV parser (workers/pcdoctor_analysis/presentmon.py).

A PresentMon file comes straight from an upload. The parser's contract, from
its docstrings and from how loader.py calls it:

* it returns FrameData, or raises PresentMonError - nothing else;
* every frame time it returns is a real, positive number;
* the statistics and the chart series computed from it are finite numbers.
"""

from __future__ import annotations

import io
import json
import math

from hypothesis import given
from hypothesis import strategies as st
from pcdoctor_analysis.presentmon import (
    FrameData,
    PresentMonError,
    compute_frame_stats,
    parse_presentmon_csv,
)
from pcdoctor_analysis.series import frame_series

import strategies
from harness import tolerate


def check_presentmon(text: str, target: str | None) -> None:
    try:
        data = parse_presentmon_csv(io.StringIO(text, newline=""), target)
    except PresentMonError:
        return  # the documented way to say "not a usable capture"
    except Exception as error:  # noqa: BLE001 - any other type is a finding
        tolerate(error)
        return
    assert isinstance(data, FrameData)
    assert data.frame_times_ms, "FrameData with no frames should have been an error"
    assert all(math.isfinite(ft) and ft > 0 for ft in data.frame_times_ms)
    assert len(data.elapsed_s) == len(data.frame_times_ms)
    assert data.other_applications >= 0
    for busy in (data.gpu_busy_ms, data.cpu_busy_ms):
        assert busy is None or len(busy) == len(data.frame_times_ms)
    try:
        stats = compute_frame_stats(data).to_dict()
        series = frame_series(data)
        # Both are stored as JSON by the API; NaN and Infinity are not JSON.
        json.dumps([stats, series], allow_nan=False)
    except Exception as error:  # noqa: BLE001
        tolerate(error)
        return
    assert stats["frames"] == len(data.frame_times_ms)
    assert stats["spike_count"] >= stats["hitch_count"] >= 0


@given(strategies.presentmon_text(), st.one_of(st.none(), st.sampled_from(["game", "dwm.exe", ""])))
def test_presentmon_parser(text: str, target: str | None) -> None:
    check_presentmon(text, target)


@given(st.binary(max_size=600))
def test_presentmon_parser_random_bytes(raw: bytes) -> None:
    # Decoded the way parse_presentmon_csv decodes a file on disk.
    check_presentmon(raw.decode("utf-8-sig", errors="replace"), None)
