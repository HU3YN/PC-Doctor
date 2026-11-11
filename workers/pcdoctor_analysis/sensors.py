"""Read the collector's sensors.csv.

The collector writes one row per sample with fixed column names, whatever tool
the numbers came from (LibreHardwareMonitor, nvidia-smi or Windows performance
counters). A column the PC could not provide is simply empty.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .presentmon import percentile

# column -> (label, unit). The order is the order charts and tables use.
SENSOR_COLUMNS: dict[str, tuple[str, str]] = {
    "cpu_temp_c": ("CPU temperature", "°C"),
    "cpu_load_pct": ("CPU load", "%"),
    "cpu_core_max_load_pct": ("Busiest CPU core", "%"),
    "cpu_clock_mhz": ("CPU clock", "MHz"),
    "cpu_perf_pct": ("CPU speed vs. rated", "%"),
    "cpu_power_w": ("CPU power", "W"),
    "gpu_temp_c": ("GPU temperature", "°C"),
    "gpu_hotspot_c": ("GPU hot spot", "°C"),
    "gpu_load_pct": ("GPU load", "%"),
    "gpu_clock_mhz": ("GPU clock", "MHz"),
    "gpu_power_w": ("GPU power", "W"),
    "gpu_fan_rpm": ("GPU fan", "RPM"),
    "gpu_vram_used_pct": ("VRAM used", "%"),
    "ram_used_pct": ("RAM used", "%"),
}

# Values outside these ranges are sensor glitches (a temperature of 0 or 255
# is a classic one) and are dropped rather than analysed.
VALID_RANGES: dict[str, tuple[float, float]] = {
    "cpu_temp_c": (1.0, 150.0),
    "gpu_temp_c": (1.0, 150.0),
    "gpu_hotspot_c": (1.0, 150.0),
    "cpu_load_pct": (0.0, 100.0),
    "cpu_core_max_load_pct": (0.0, 100.0),
    "gpu_load_pct": (0.0, 100.0),
    "gpu_vram_used_pct": (0.0, 100.0),
    "ram_used_pct": (0.0, 100.0),
    "cpu_clock_mhz": (50.0, 10000.0),
    "gpu_clock_mhz": (1.0, 10000.0),
    "cpu_perf_pct": (1.0, 400.0),
    "cpu_power_w": (0.0, 1500.0),
    "gpu_power_w": (0.0, 1500.0),
    "gpu_fan_rpm": (0.0, 20000.0),
}


@dataclass
class SensorData:
    elapsed_s: list[float]
    series: dict[str, list[float | None]]  # column -> one value per sample
    notes: list[str] = field(default_factory=list)

    def values(self, column: str) -> list[float]:
        """All readings of a column, without the gaps."""
        return [v for v in self.series.get(column, []) if v is not None]

    def has(self, column: str, minimum: int = 3) -> bool:
        return len(self.values(column)) >= minimum

    @property
    def samples(self) -> int:
        return len(self.elapsed_s)


def _number(text: str | None) -> float | None:
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    # Some Windows locales write decimals with a comma.
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value == value else None  # drop NaN


def parse_sensors_csv(path: str | Path) -> SensorData:
    elapsed: list[float] = []
    series: dict[str, list[float | None]] = {}
    dropped: dict[str, int] = {}
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as handle:
        reader = csv.DictReader(handle)
        fields = [f.strip() for f in (reader.fieldnames or [])]
        known = [f for f in fields if f in SENSOR_COLUMNS]
        for column in known:
            series[column] = []
        for row_number, row in enumerate(reader):
            row = {(k or "").strip(): v for k, v in row.items()}
            t = _number(row.get("elapsed_s"))
            elapsed.append(t if t is not None else float(row_number))
            for column in known:
                value = _number(row.get(column))
                if value is not None:
                    low, high = VALID_RANGES[column]
                    if not low <= value <= high:
                        dropped[column] = dropped.get(column, 0) + 1
                        value = None
                series[column].append(value)
    notes = [
        f"{count} out-of-range {SENSOR_COLUMNS[column][0].lower()} readings were ignored."
        for column, count in dropped.items()
    ]
    # Drop columns that never had a reading so "has data" checks stay simple.
    series = {c: v for c, v in series.items() if any(x is not None for x in v)}
    return SensorData(elapsed_s=elapsed, series=series, notes=notes)


def summarize(data: SensorData) -> dict[str, dict[str, Any]]:
    """min / average / 95th percentile / max for every column with data."""
    out: dict[str, dict[str, Any]] = {}
    for column, (label, unit) in SENSOR_COLUMNS.items():
        values = data.values(column)
        if not values:
            continue
        ordered = sorted(values)
        out[column] = {
            "label": label,
            "unit": unit,
            "min": round(ordered[0], 1),
            "avg": round(sum(values) / len(values), 1),
            "p95": round(percentile(ordered, 95), 1),
            "max": round(ordered[-1], 1),
            "samples": len(values),
        }
    return out
