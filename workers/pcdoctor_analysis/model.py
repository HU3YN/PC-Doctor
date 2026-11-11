"""Shared data types: findings, severities and fault categories."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    """How much a finding matters.

    critical: hardware is failing, data is at risk, or the PC is unstable.
    warning:  a real problem that hurts performance or reliability.
    info:     worth knowing; often explains the numbers rather than a fault.
    """

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"

    @property
    def rank(self) -> int:
        return {"critical": 3, "warning": 2, "info": 1}[self.value]


# Fault categories. The work log uses the same list so that a logged repair
# and an automatic finding can be matched to each other.
CATEGORIES: dict[str, str] = {
    "thermal": "Thermal / cooling",
    "power": "Power / PSU",
    "memory": "Memory (RAM)",
    "storage": "Storage (SSD / HDD)",
    "gpu": "Graphics card",
    "cpu": "Processor",
    "motherboard": "Motherboard / BIOS",
    "driver": "Driver",
    "os": "Windows / software",
    "performance": "Performance",
    "network": "Network",
    "peripheral": "Peripheral / display",
    "no_fault_found": "No fault found",
    "other": "Other",
}


@dataclass
class Finding:
    """One thing the rules engine found, written for a person to read."""

    code: str  # stable id, e.g. "thermal.cpu_hot"
    category: str  # key of CATEGORIES
    severity: Severity
    title: str  # one line
    summary: str  # plain English, the way a technician would explain it
    next_checks: list[str] = field(default_factory=list)  # what to do next, in order
    evidence: dict[str, Any] = field(default_factory=dict)  # the numbers behind it
    # Stop codes / event ids involved, e.g. ["0x124", "WHEA-18"]. Used to find
    # earlier work-log cases with the same code.
    error_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass(frozen=True)
class Thresholds:
    """Every number the rules compare against, in one place.

    These are starting values from common technician practice and component
    limits. They are meant to be tuned against the labeled fault set (Phase 2);
    docs/rules.md explains each one.
    """

    # --- frame times
    spike_ratio: float = 2.0  # a spike is a frame > this x the recent median...
    spike_min_extra_ms: float = 8.0  # ...and at least this much longer than it
    spike_window_frames: int = 30  # "recent" = this many previous frames
    hitch_ms: float = 100.0  # a spike this long is a hitch you clearly feel
    stutter_spikes_per_min_warn: float = 4.0
    stutter_low_ratio_warn: float = 0.45  # 1% low below this share of the average
    min_frames_for_stats: int = 300
    # --- bottleneck
    gpu_limited_load_pct: float = 95.0
    cpu_limited_gpu_load_below_pct: float = 85.0
    cpu_limited_core_load_pct: float = 85.0
    # --- temperatures (deg C)
    cpu_temp_warn_c: float = 90.0
    cpu_temp_crit_c: float = 100.0
    cpu_temp_sustained_c: float = 85.0
    cpu_temp_sustained_share: float = 0.25  # share of the run above the line
    gpu_temp_warn_c: float = 87.0
    gpu_temp_crit_c: float = 95.0
    gpu_hotspot_warn_c: float = 100.0
    gpu_hotspot_crit_c: float = 110.0
    ssd_temp_warn_c: float = 70.0
    hdd_temp_warn_c: float = 55.0
    # --- throttling
    throttle_hot_c: float = 90.0
    throttle_cool_c: float = 85.0
    throttle_clock_drop: float = 0.15  # clock at least 15% lower when hot
    throttle_min_samples: int = 5
    throttle_min_load_pct: float = 50.0
    gpu_throttle_hot_c: float = 84.0
    gpu_throttle_cool_c: float = 78.0
    gpu_throttle_min_load_pct: float = 90.0
    # --- memory / vram
    ram_used_warn_pct: float = 95.0
    vram_used_warn_pct: float = 97.0
    # --- storage
    ssd_wear_warn_pct: float = 80.0
    ssd_wear_crit_pct: float = 95.0
    low_space_free_share: float = 0.10
    low_space_system_free_gb: float = 15.0
    low_space_min_volume_gb: float = 8.0  # ignore recovery / EFI partitions
    # --- events
    unexpected_shutdowns_crit: int = 3
    bluescreens_crit: int = 3
    whea_corrected_warn: int = 1
    display_driver_resets_warn: int = 1
    # --- system
    gpu_driver_old_months: int = 18
    battery_wear_warn_pct: float = 40.0  # capacity lost versus design
