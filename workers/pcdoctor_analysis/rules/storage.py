"""Disk health, wear, temperature and free-space rules (from disks.json)."""

from __future__ import annotations

import math
from typing import Any

from ..loader import RunData
from ..model import Finding, Severity, Thresholds
from . import rule

GB = 1024**3


def _number(value: Any) -> float | None:
    """A finite number, or None. JSON from a stranger can hold 1e999 or a
    300-digit integer; neither may reach a rule or the stored result."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value) if isinstance(value, (int, float)) else float(str(value).strip())
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _disks(run: RunData) -> list[dict[str, Any]]:
    return run.disks.get("physical_disks", []) if run.disks else []


def _name(disk: dict[str, Any]) -> str:
    return str(disk.get("name") or "Unnamed disk").strip()


def _reliability(disk: dict[str, Any]) -> dict[str, Any]:
    data = disk.get("reliability")
    return data if isinstance(data, dict) else {}


@rule(
    "storage.disk_unhealthy",
    "storage",
    "Disk health status",
    "Windows reports a disk as unhealthy, or the disk has uncorrectable errors.",
    "disk health from the collector",
)
def disk_unhealthy(run: RunData, t: Thresholds) -> list[Finding] | None:
    disks = _disks(run)
    if not disks:
        return None
    findings: list[Finding] = []
    for disk in disks:
        health = str(disk.get("health_status") or "").strip()
        rel = _reliability(disk)
        read_bad = _number(rel.get("read_errors_uncorrected")) or 0
        write_bad = _number(rel.get("write_errors_uncorrected")) or 0
        bad_health = health.lower() in ("warning", "unhealthy")
        if not bad_health and read_bad <= 0 and write_bad <= 0:
            continue
        critical = health.lower() == "unhealthy" or read_bad > 0 or write_bad > 0
        reasons = []
        if bad_health:
            reasons.append(f"Windows reports its health as '{health}'")
        if read_bad > 0:
            reasons.append(f"{read_bad:.0f} uncorrectable read error(s)")
        if write_bad > 0:
            reasons.append(f"{write_bad:.0f} uncorrectable write error(s)")
        findings.append(
            Finding(
                code="storage.disk_unhealthy",
                category="storage",
                severity=Severity.CRITICAL if critical else Severity.WARNING,
                title=f"Disk is failing: {_name(disk)}",
                summary=(
                    f"{_name(disk)}: {'; '.join(reasons)}. A drive in this state can stop "
                    "working without further warning. Uncorrectable errors mean it has already "
                    "failed to read or write data."
                ),
                next_checks=[
                    "Back up the data now, before any more testing.",
                    "Confirm with the drive maker's tool (full SMART report).",
                    "Replace the drive; clone it only if the clone finishes without read errors.",
                ],
                evidence={
                    "disk": _name(disk),
                    "health_status": health,
                    "operational_status": disk.get("operational_status"),
                    "read_errors_uncorrected": read_bad,
                    "write_errors_uncorrected": write_bad,
                    "power_on_hours": rel.get("power_on_hours"),
                },
            )
        )
    return findings


@rule(
    "storage.ssd_worn",
    "storage",
    "SSD wear",
    "An SSD has used most of its rated write life.",
    "disk reliability counters (needs administrator)",
)
def ssd_worn(run: RunData, t: Thresholds) -> list[Finding] | None:
    disks = [d for d in _disks(run) if _number(_reliability(d).get("wear_pct")) is not None]
    if not disks:
        return None
    findings: list[Finding] = []
    for disk in disks:
        wear = _number(_reliability(disk).get("wear_pct")) or 0.0
        if wear < t.ssd_wear_warn_pct:
            continue
        findings.append(
            Finding(
                code="storage.ssd_worn",
                category="storage",
                severity=Severity.CRITICAL if wear >= t.ssd_wear_crit_pct else Severity.WARNING,
                title=f"SSD is {wear:.0f}% worn: {_name(disk)}",
                summary=(
                    f"{_name(disk)} reports {wear:.0f}% wear - the share of its rated write "
                    "life already used. Past the rated life an SSD can slow down, turn "
                    "read-only, or fail outright."
                ),
                next_checks=[
                    "Make sure the data is backed up.",
                    "Plan a replacement; do not use this drive for anything that matters.",
                    "Confirm the figure with the drive maker's tool.",
                ],
                evidence={
                    "disk": _name(disk),
                    "wear_pct": wear,
                    "power_on_hours": _reliability(disk).get("power_on_hours"),
                },
            )
        )
    return findings


@rule(
    "storage.drive_hot",
    "thermal",
    "Drive temperature",
    "A drive runs hot enough to slow itself down or wear faster.",
    "disk reliability counters (needs administrator)",
)
def drive_hot(run: RunData, t: Thresholds) -> list[Finding] | None:
    readings = []
    for disk in _disks(run):
        temp = _number(_reliability(disk).get("temperature_c"))
        if temp is not None and 1 <= temp <= 150:  # 0 means "not reported"
            readings.append((disk, temp))
    if not readings:
        return None
    findings: list[Finding] = []
    for disk, temp in readings:
        is_hdd = str(disk.get("media_type") or "").upper() == "HDD"
        limit = t.hdd_temp_warn_c if is_hdd else t.ssd_temp_warn_c
        if temp < limit:
            continue
        findings.append(
            Finding(
                code="storage.drive_hot",
                category="thermal",
                severity=Severity.WARNING,
                title=f"Drive running hot: {_name(disk)} at {temp:.0f} °C",
                summary=(
                    f"{_name(disk)} reported {temp:.0f} °C. "
                    + (
                        "Hard drives wear much faster above 50-55 °C."
                        if is_hdd
                        else "NVMe drives throttle their speed when hot, which shows up as "
                        "long pauses while loading or copying."
                    )
                ),
                next_checks=[
                    "Fit the motherboard's M.2 heatsink (and remove the plastic film from its "
                    "thermal pad)."
                    if not is_hdd
                    else "Check airflow over the drive bays.",
                    "Move the drive away from the graphics card's exhaust if there is another "
                    "slot.",
                    "Improve case airflow.",
                ],
                evidence={"disk": _name(disk), "temperature_c": temp, "limit_c": limit},
            )
        )
    return findings


@rule(
    "storage.low_space",
    "storage",
    "Free disk space",
    "A volume is almost full.",
    "volume sizes from the collector",
)
def low_space(run: RunData, t: Thresholds) -> list[Finding] | None:
    volumes = run.disks.get("volumes", []) if run.disks else []
    usable = []
    for volume in volumes:
        size = _number(volume.get("size_bytes"))
        free = _number(volume.get("free_bytes"))
        letter = str(volume.get("drive_letter") or "").strip()
        if not letter or size is None or free is None:
            continue
        if size < t.low_space_min_volume_gb * GB:
            continue
        usable.append((letter, size, free, bool(volume.get("is_system"))))
    if not usable:
        return None
    findings: list[Finding] = []
    for letter, size, free, is_system in usable:
        share = free / size if size else 1.0
        low_share = share < t.low_space_free_share
        low_system = is_system and free < t.low_space_system_free_gb * GB
        if not (low_share or low_system):
            continue
        summary = (
            f"Drive {letter}: has {free / GB:.1f} GB free of {size / GB:.0f} GB "
            f"({share:.0%} free). "
        )
        if is_system:
            summary += (
                "This is the Windows drive: when it runs out of room, updates fail, the page "
                "file cannot grow, and programs crash or stutter."
            )
        else:
            summary += "A nearly full SSD also gets slower, because it has no spare room to work."
        findings.append(
            Finding(
                code="storage.low_space",
                category="storage",
                severity=Severity.WARNING,
                title=f"Drive {letter}: is almost full ({free / GB:.1f} GB free)",
                summary=summary,
                next_checks=[
                    "Run Disk Cleanup / Storage Sense, including 'Clean up system files'.",
                    "Uninstall unused games and programs, or move them to another drive.",
                    "Keep at least 15-20% of an SSD free.",
                ],
                evidence={
                    "drive": letter,
                    "free_gb": round(free / GB, 1),
                    "size_gb": round(size / GB, 1),
                    "free_share": round(share, 3),
                    "is_system": is_system,
                },
            )
        )
    return findings
