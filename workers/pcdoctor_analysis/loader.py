"""Load a collector run folder into memory.

A run folder is what the Windows collector writes (docs/run-format.md):

    manifest.json   what was collected, when, and with which tools
    specs.json      the PC's parts and Windows version
    events.json     hardware-related events from the Windows event log
    disks.json      disk health and free space
    presentmon.csv  frame times (capture runs only)
    sensors.csv     temperatures, loads, clocks (capture runs only)

Every file is optional. A missing or damaged file becomes a note, never a
crash: a technician should still get whatever the rest of the run can tell.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .presentmon import FrameData, PresentMonError, parse_presentmon_csv
from .sensors import SensorData, parse_sensors_csv

SUPPORTED_SCHEMA_VERSIONS = (1,)
MAX_JSON_BYTES = 20 * 1024 * 1024


@dataclass
class RunData:
    manifest: dict[str, Any] = field(default_factory=dict)
    specs: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    events_collected: bool = False  # False = the event log was not read at all
    event_window_days: int | None = None
    disks: dict[str, Any] = field(default_factory=dict)
    frames: FrameData | None = None
    sensors: SensorData | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def captured_at(self) -> datetime | None:
        return parse_time(self.manifest.get("started_at"))

    # ---- small helpers the rules share

    def events_from(
        self, provider: str, ids: tuple[int, ...] | None = None
    ) -> list[dict[str, Any]]:
        """Events of one provider (exact name, case-insensitive), optionally by id."""
        wanted = provider.lower()
        out = []
        for event in self.events:
            if str(event.get("provider", "")).lower() != wanted:
                continue
            if ids is not None and event.get("id") not in ids:
                continue
            out.append(event)
        return out


def parse_time(value: Any) -> datetime | None:
    """Parse an ISO-8601 time; None when missing or unreadable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _read_json(path: Path, notes: list[str]) -> Any:
    if not path.is_file():
        return None
    if path.stat().st_size > MAX_JSON_BYTES:
        notes.append(f"{path.name} is too large to read and was skipped.")
        return None
    try:
        # utf-8-sig: Windows PowerShell 5.1 writes a byte-order mark.
        return json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except (json.JSONDecodeError, OSError) as error:
        notes.append(f"{path.name} could not be read ({error.__class__.__name__}).")
        return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    """PowerShell's ConvertTo-Json turns a one-item list into a bare object."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def normalize_specs(specs: dict[str, Any]) -> dict[str, Any]:
    """Make list-valued spec fields real lists (see _as_list)."""
    specs = dict(specs)
    for key in ("cpu", "gpu"):
        specs[key] = [x for x in _as_list(specs.get(key)) if isinstance(x, dict)]
    memory = _as_dict(specs.get("memory"))
    memory["modules"] = [x for x in _as_list(memory.get("modules")) if isinstance(x, dict)]
    specs["memory"] = memory
    return specs


def load_run_dir(path: str | Path) -> RunData:
    root = Path(path)
    if not root.is_dir():
        raise FileNotFoundError(f"Run folder not found: {root}")

    run = RunData()
    notes = run.notes

    run.manifest = _as_dict(_read_json(root / "manifest.json", notes))
    if not run.manifest:
        notes.append("manifest.json is missing, so the capture time and settings are unknown.")
    else:
        version = run.manifest.get("schema_version")
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            notes.append(
                f"This run uses format version {version!r}, which this analyzer does not know. "
                "Results may be incomplete - update PC Doctor."
            )
        for warning in _as_list(run.manifest.get("warnings")):
            if isinstance(warning, str) and warning.strip():
                notes.append(f"Collector: {warning.strip()}")

    specs = _read_json(root / "specs.json", notes)
    run.specs = normalize_specs(_as_dict(specs))

    events_doc = _read_json(root / "events.json", notes)
    if isinstance(events_doc, dict):
        run.events_collected = True
        run.events = [e for e in _as_list(events_doc.get("events")) if isinstance(e, dict)]
        window = events_doc.get("window_days")
        run.event_window_days = window if isinstance(window, int) else None
        for error in _as_list(events_doc.get("errors")):
            if isinstance(error, str) and error.strip():
                notes.append(f"Event log: {error.strip()}")

    disks = _as_dict(_read_json(root / "disks.json", notes))
    if disks:
        disks["physical_disks"] = [
            d for d in _as_list(disks.get("physical_disks")) if isinstance(d, dict)
        ]
        disks["volumes"] = [v for v in _as_list(disks.get("volumes")) if isinstance(v, dict)]
    run.disks = disks

    capture = _as_dict(run.manifest.get("capture"))
    target = capture.get("target_process")
    presentmon = root / "presentmon.csv"
    if presentmon.is_file() and presentmon.stat().st_size > 0:
        try:
            run.frames = parse_presentmon_csv(
                presentmon, target if isinstance(target, str) else None
            )
            notes.extend(run.frames.notes)
        except PresentMonError as error:
            notes.append(f"Frame times: {error}")

    sensors = root / "sensors.csv"
    if sensors.is_file() and sensors.stat().st_size > 0:
        try:
            run.sensors = parse_sensors_csv(sensors)
            notes.extend(run.sensors.notes)
            if run.sensors.samples == 0:
                run.sensors = None
        except (OSError, ValueError) as error:
            notes.append(f"Sensors: could not read sensors.csv ({error}).")

    return run
