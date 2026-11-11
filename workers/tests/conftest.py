from __future__ import annotations

from typing import Any

import pytest

from pcdoctor_analysis.loader import RunData, normalize_specs
from pcdoctor_analysis.presentmon import FrameData
from pcdoctor_analysis.sensors import SensorData


def make_frames(frame_times: list[float], **kwargs: Any) -> FrameData:
    elapsed, running = [], 0.0
    for ft in frame_times:
        elapsed.append(running)
        running += ft / 1000.0
    return FrameData(
        application="game.exe", frame_times_ms=frame_times, elapsed_s=elapsed, **kwargs
    )


def make_sensors(**columns: list[float | None]) -> SensorData:
    length = max(len(v) for v in columns.values())
    return SensorData(elapsed_s=[float(i) for i in range(length)], series=dict(columns))


def make_run(
    *,
    specs: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
    disks: dict[str, Any] | None = None,
    frames: FrameData | None = None,
    sensors: SensorData | None = None,
) -> RunData:
    return RunData(
        manifest={"schema_version": 1, "started_at": "2026-11-01T18:00:00Z"},
        specs=normalize_specs(specs or {}),
        events=events or [],
        events_collected=events is not None,
        event_window_days=30,
        disks=disks or {},
        frames=frames,
        sensors=sensors,
    )


def event(provider: str, event_id: int, message: str = "", level: str = "Error", **data: Any):
    return {
        "time": "2026-10-30T12:00:00Z",
        "provider": provider,
        "id": event_id,
        "level": level,
        "message": message,
        "data": {k: str(v) for k, v in data.items()},
    }


@pytest.fixture
def run_factory():
    return make_run
