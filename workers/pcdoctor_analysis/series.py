"""Shrink time series so a chart can draw them quickly.

A five-minute capture at 144 FPS is about 43,000 frames. A chart cannot show
more points than it has pixels, so frames are grouped into buckets. Each
bucket keeps its average and its worst frame, so a single long frame is never
smoothed away - which is the whole point of a frame-time chart.
"""

from __future__ import annotations

from typing import Any

from .presentmon import FrameData
from .sensors import SensorData


def frame_series(data: FrameData, max_points: int = 1200) -> dict[str, list[float]]:
    n = len(data.frame_times_ms)
    if n == 0:
        return {"t": [], "avg_ms": [], "max_ms": []}
    step = max(1, -(-n // max_points))  # ceiling division
    t: list[float] = []
    avg: list[float] = []
    worst: list[float] = []
    for start in range(0, n, step):
        chunk = data.frame_times_ms[start : start + step]
        t.append(round(data.elapsed_s[start], 3))
        avg.append(round(sum(chunk) / len(chunk), 3))
        worst.append(round(max(chunk), 3))
    return {"t": t, "avg_ms": avg, "max_ms": worst}


def sensor_series(data: SensorData, max_points: int = 1200) -> dict[str, Any]:
    n = data.samples
    if n == 0:
        return {"t": []}
    step = max(1, -(-n // max_points))
    out: dict[str, Any] = {"t": [round(data.elapsed_s[i], 2) for i in range(0, n, step)]}
    for column, values in data.series.items():
        points: list[float | None] = []
        for start in range(0, n, step):
            chunk = [v for v in values[start : start + step] if v is not None]
            # Keep the peak of each bucket: for temperatures and loads the
            # maximum is the number that matters.
            points.append(round(max(chunk), 2) if chunk else None)
        out[column] = points
    return out
