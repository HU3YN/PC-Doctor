"""Synthetic sample runs.

These are made-up runs in the collector's exact file format. They exist so
that the tests, the dashboard demo and the evaluation harness have something
to work on before real captures exist.

They are NOT measurements. Never quote a number from a synthetic run as a
result: a rule that catches a fault it was written to catch proves the
plumbing works, not that the diagnosis is accurate on real hardware. Real
labeled captures (docs/fault-testing.md) replace these in Phase 2.
"""

from __future__ import annotations

import csv
import io
import json
import math
import random
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .sensors import SENSOR_COLUMNS

BASE_TIME = datetime(2026, 11, 1, 18, 0, 0, tzinfo=UTC)
GB = 1024**3

PRESENTMON_HEADER = [
    "Application",
    "ProcessID",
    "SwapChainAddress",
    "PresentRuntime",
    "SyncInterval",
    "PresentFlags",
    "AllowsTearing",
    "PresentMode",
    "TimeInSeconds",
    "MsBetweenSimulationStart",
    "MsBetweenPresents",
    "MsBetweenDisplayChange",
    "MsInPresentAPI",
    "MsRenderPresentLatency",
    "MsUntilDisplayed",
    "CPUStartTimeInSeconds",
    "MsBetweenAppStart",
    "MsCPUBusy",
    "MsCPUWait",
    "MsGPULatency",
    "MsGPUTime",
    "MsGPUBusy",
    "MsGPUWait",
]


@dataclass
class SampleRun:
    """The files of one run, held in memory."""

    name: str
    title: str
    description: str
    expected: list[str]  # finding codes a correct diagnosis must include
    files: dict[str, str] = field(default_factory=dict)

    def write(self, directory: str | Path) -> Path:
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        for filename, content in self.files.items():
            (root / filename).write_text(content, encoding="utf-8", newline="")
        return root

    def zip_bytes(self) -> bytes:
        """The run as a zip. Byte-for-byte the same every time it is built."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for filename, content in self.files.items():
                # A fixed timestamp: writestr() would stamp "now" otherwise.
                info = zipfile.ZipInfo(filename, date_time=(2026, 11, 1, 18, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, content)
        return buffer.getvalue()


# ------------------------------------------------------------------ pieces


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _specs(
    *,
    cpu: str = "AMD Ryzen 7 5800X 8-Core Processor",
    cores: int = 8,
    gpu: str = "NVIDIA GeForce RTX 3070",
    vram_gb: int = 8,
    driver_date: str = "2026-09-18T00:00:00Z",
    driver_version: str = "32.0.15.7283",
    sticks: int = 2,
    stick_gb: int = 16,
    ram_type: str = "DDR4",
    rated: int = 3600,
    configured: int = 3600,
    part_numbers: list[str] | None = None,
    slots: int = 4,
    board: tuple[str, str] = ("Micro-Star International Co., Ltd.", "B550 TOMAHAWK"),
    system_type: str = "desktop",
    power_plan: tuple[str, str] = ("Balanced", "381b4222-f694-41f0-9685-ff5bb260df2e"),
    battery: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parts = part_numbers or ["F4-3600C16-16GVKC"] * sticks
    locators = ["DIMM_A2", "DIMM_B2", "DIMM_A1", "DIMM_B1"]
    return {
        "os": {
            "caption": "Microsoft Windows 11 Home",
            "version": "10.0.26100",
            "build": "26100",
            "architecture": "64-bit",
            "last_boot": _iso(BASE_TIME - timedelta(hours=5)),
            "uptime_hours": 5.0,
        },
        "system": {
            "manufacturer": board[0] if system_type == "desktop" else "LENOVO",
            "model": "MS-7C91" if system_type == "desktop" else "Legion 5 15ACH6H",
            "type": system_type,
        },
        "cpu": [
            {
                "name": cpu,
                "manufacturer": "AuthenticAMD" if "AMD" in cpu else "GenuineIntel",
                "cores": cores,
                "threads": cores * 2,
                "max_clock_mhz": 3800,
            }
        ],
        "gpu": [
            {
                "name": gpu,
                "driver_version": driver_version,
                "driver_date": driver_date,
                "vram_bytes": vram_gb * GB,
                "resolution": "2560x1440",
                "refresh_hz": 144,
            }
        ],
        "displays": [
            {
                "adapter": gpu,
                "resolution": "2560x1440",
                "refresh_hz": 144,
                "max_refresh_hz_at_resolution": 144,
                "max_refresh_hz": 165,
                "monitor": "Example 27Q",
                "monitor_max_refresh_hz": 165,
            }
        ],
        "memory": {
            "total_bytes": sticks * stick_gb * GB,
            "slots_total": slots,
            "modules": [
                {
                    "slot": locators[i % 4],
                    "capacity_bytes": stick_gb * GB,
                    "speed_mhz": rated,
                    "configured_speed_mhz": configured,
                    "manufacturer": "G.Skill",
                    "part_number": parts[i],
                    "type": ram_type,
                    "form_factor": "DIMM" if system_type == "desktop" else "SODIMM",
                }
                for i in range(sticks)
            ],
        },
        "motherboard": {"manufacturer": board[0], "product": board[1], "version": "1.0"},
        "bios": {
            "vendor": "American Megatrends International, LLC.",
            "version": "A.F0",
            "release_date": "2025-03-12T00:00:00Z",
        },
        "power_plan": power_plan[0],
        "power_plan_guid": power_plan[1],
        "battery": battery,
    }


def _disk(
    name: str = "Samsung SSD 980 PRO 1TB",
    *,
    media: str = "SSD",
    bus: str = "NVMe",
    health: str = "Healthy",
    size_gb: int = 931,
    temp: int | None = 42,
    wear: int | None = 4,
    read_bad: int = 0,
    write_bad: int = 0,
    hours: int = 6100,
) -> dict[str, Any]:
    return {
        "name": name,
        "media_type": media,
        "bus_type": bus,
        "health_status": health,
        "operational_status": "OK" if health == "Healthy" else "Predictive Failure",
        "size_bytes": size_gb * GB,
        "firmware": "5B2QGXA7",
        "reliability": {
            "temperature_c": temp,
            "temperature_max_c": 70 if temp is not None else None,
            "wear_pct": wear,
            "read_errors_total": read_bad,
            "read_errors_uncorrected": read_bad,
            "write_errors_total": write_bad,
            "write_errors_uncorrected": write_bad,
            "power_on_hours": hours,
        },
    }


def _volume(letter: str, size_gb: float, free_gb: float, system: bool = False) -> dict[str, Any]:
    return {
        "drive_letter": letter,
        "file_system": "NTFS",
        "size_bytes": int(size_gb * GB),
        "free_bytes": int(free_gb * GB),
        "health_status": "Healthy",
        "is_system": system,
    }


def _disks(
    disks: list[dict[str, Any]] | None = None, volumes: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "physical_disks": disks or [_disk()],
        "volumes": volumes or [_volume("C", 930, 412, True)],
    }


def _event(
    days_ago: float, provider: str, event_id: int, level: str, message: str, **data: Any
) -> dict[str, Any]:
    return {
        "time": _iso(BASE_TIME - timedelta(days=days_ago)),
        "provider": provider,
        "id": event_id,
        "level": level,
        "log": "System",
        "message": message,
        "data": {key: str(value) for key, value in data.items()},
    }


def _events(events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    ordered = sorted(events or [], key=lambda e: e["time"])
    return {"window_days": 30, "collected_at": _iso(BASE_TIME), "events": ordered, "errors": []}


def _manifest(mode: str, label: str, seconds: int = 0, samples: int = 0) -> dict[str, Any]:
    capture = None
    if mode == "capture":
        capture = {
            "requested_seconds": seconds,
            "actual_seconds": float(seconds),
            "target_process": None,
            "presentmon": {"used": True, "version": "2.6.0", "file": "presentmon.csv"},
            "sensors": {
                "source": "librehardwaremonitor",
                "interval_seconds": 1,
                "file": "sensors.csv",
                "samples": samples,
            },
        }
    return {
        "schema_version": 1,
        "run_id": f"synthetic-{label.lower().replace(' ', '-')}",
        "collector": {"name": "pcdoctor-synth", "version": "0.1.0"},
        "started_at": _iso(BASE_TIME),
        "finished_at": _iso(BASE_TIME + timedelta(seconds=seconds or 20)),
        "mode": mode,
        "label": label,
        "synthetic": True,
        "capture": capture,
        "event_window_days": 30,
        "is_admin": True,
        "warnings": [],
    }


def _frames_csv(
    rng: random.Random,
    seconds: int,
    fps: Callable[[float], float],
    *,
    jitter: float = 0.06,
    spike_every_s: float | None = None,
    spike_ms: tuple[float, float] = (45.0, 140.0),
    gpu_busy_share: float = 0.92,
    app: str = "SampleGame.exe",
) -> str:
    """A PresentMon-style CSV. ``fps`` gives the target frame rate at time t."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(PRESENTMON_HEADER)
    t = 0.0
    next_spike = rng.uniform(0.5, 1.5) * spike_every_s if spike_every_s else math.inf
    while t < seconds:
        frame_ms = 1000.0 / fps(t) * math.exp(rng.gauss(0.0, jitter))
        if t >= next_spike:
            frame_ms = rng.uniform(*spike_ms)
            next_spike = t + rng.uniform(0.4, 1.6) * (spike_every_s or 1.0)
        gpu_busy = frame_ms * min(0.99, gpu_busy_share * rng.uniform(0.97, 1.03))
        cpu_busy = frame_ms * rng.uniform(0.35, 0.55)
        writer.writerow(
            [
                app,
                9184,
                "0x000001E2A3B4C5D0",
                "DXGI",
                0,
                512,
                1,
                "Hardware: Independent Flip",
                f"{t:.6f}",
                f"{frame_ms:.4f}",
                f"{frame_ms:.4f}",
                f"{frame_ms:.4f}",
                "0.4100",
                f"{frame_ms * 0.6:.4f}",
                f"{frame_ms * 1.4:.4f}",
                f"{t:.6f}",
                f"{frame_ms:.4f}",
                f"{cpu_busy:.4f}",
                f"{frame_ms - cpu_busy:.4f}",
                "1.2000",
                f"{gpu_busy:.4f}",
                f"{gpu_busy:.4f}",
                f"{frame_ms - gpu_busy:.4f}",
            ]
        )
        t += frame_ms / 1000.0
    return out.getvalue()


def _sensors_csv(seconds: int, sample: Callable[[int], dict[str, float]]) -> str:
    out = io.StringIO()
    columns = ["elapsed_s", *SENSOR_COLUMNS]
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for second in range(seconds):
        row = {key: f"{value:.1f}" for key, value in sample(second).items()}
        row["elapsed_s"] = str(second)
        writer.writerow(row)
    return out.getvalue()


def _dump(value: Any) -> str:
    return json.dumps(value, indent=2) + "\n"


def _assemble(
    name: str,
    title: str,
    description: str,
    expected: list[str],
    *,
    mode: str,
    specs: dict[str, Any],
    events: dict[str, Any],
    disks: dict[str, Any],
    frames: str | None = None,
    sensors: str | None = None,
    seconds: int = 0,
) -> SampleRun:
    files = {
        "manifest.json": _dump(_manifest(mode, title, seconds, seconds)),
        "specs.json": _dump(specs),
        "events.json": _dump(events),
        "disks.json": _dump(disks),
    }
    if frames is not None:
        files["presentmon.csv"] = frames
    if sensors is not None:
        files["sensors.csv"] = sensors
    return SampleRun(name, title, description, expected, files)


# --------------------------------------------------------------- scenarios

WHEA_CPU_FATAL = (
    "A fatal hardware error has occurred.\n\nReported by component: Processor Core\n"
    "Error Source: Machine Check Exception\nError Type: Cache Hierarchy Error\n"
    "Processor APIC ID: 4\n\nThe details view of this entry contains further information."
)
WHEA_MEMORY_CORRECTED = (
    "A corrected hardware error has occurred.\n\nComponent: Memory\n"
    "Error Source: Corrected Machine Check\n\n"
    "The details view of this entry contains further information."
)
KP41 = (
    "The system has rebooted without cleanly shutting down first. This error could be caused "
    "if the system stopped responding, crashed, or lost power unexpectedly."
)


def _bugcheck(days_ago: float, code: int) -> dict[str, Any]:
    parameters = "0x0000000000000000, 0xffffb08d2a4c8028, 0x00000000be000000, 0x0000000000800400"
    text = f"0x{code:08x} ({parameters})"
    return _event(
        days_ago,
        "Microsoft-Windows-WER-SystemErrorReporting",
        1001,
        "Error",
        f"The computer has rebooted from a bugcheck.  The bugcheck was: {text}. "
        "A dump was saved in: C:\\Windows\\MEMORY.DMP. "
        "Report Id: 00000000-0000-0000-0000-000000000000.",
        param1=text,
        param2="C:\\Windows\\MEMORY.DMP",
    )


def healthy(seed: int = 1) -> SampleRun:
    rng = random.Random(seed)
    seconds = 120

    def sample(s: int) -> dict[str, float]:
        warm = min(1.0, s / 40)
        return {
            "cpu_temp_c": 48 + 20 * warm + rng.uniform(-1.5, 1.5),
            "cpu_load_pct": 38 + rng.uniform(-6, 6),
            "cpu_core_max_load_pct": 66 + rng.uniform(-8, 8),
            "cpu_clock_mhz": 4650 + rng.uniform(-40, 40),
            "cpu_power_w": 78 + rng.uniform(-5, 5),
            "gpu_temp_c": 52 + 18 * warm + rng.uniform(-1, 1),
            "gpu_hotspot_c": 62 + 20 * warm + rng.uniform(-1, 1),
            "gpu_load_pct": 97 + rng.uniform(-2, 2),
            "gpu_clock_mhz": 1905 + rng.uniform(-10, 10),
            "gpu_power_w": 212 + rng.uniform(-8, 8),
            "gpu_fan_rpm": 1300 + 500 * warm,
            "gpu_vram_used_pct": 71 + rng.uniform(-2, 2),
            "ram_used_pct": 54 + rng.uniform(-1, 1),
        }

    return _assemble(
        "healthy",
        "Healthy gaming PC",
        "A well-built PC in a demanding game: steady frame times, sensible temperatures, "
        "clean event log. The only finding is that the GPU sets the frame rate, which is normal.",
        ["performance.gpu_limited"],
        mode="capture",
        specs=_specs(),
        events=_events(),
        disks=_disks(),
        frames=_frames_csv(rng, seconds, lambda t: 142 + 6 * math.sin(t / 9)),
        sensors=_sensors_csv(seconds, sample),
        seconds=seconds,
    )


def cpu_overheat(seed: int = 2) -> SampleRun:
    rng = random.Random(seed)
    seconds = 150

    def temperature(s: float) -> float:
        return min(99.0, 58 + 41 * (1 - math.exp(-s / 28)))

    def sample(s: int) -> dict[str, float]:
        temp = temperature(s) + rng.uniform(-0.8, 0.8)
        throttled = temp >= 93
        return {
            "cpu_temp_c": temp,
            "cpu_load_pct": 72 + rng.uniform(-5, 5),
            "cpu_core_max_load_pct": 96 + rng.uniform(-3, 3),
            "cpu_clock_mhz": (3350 if throttled else 4720) + rng.uniform(-60, 60),
            "cpu_power_w": (88 if throttled else 138) + rng.uniform(-5, 5),
            "gpu_temp_c": 64 + rng.uniform(-1, 1),
            "gpu_hotspot_c": 75 + rng.uniform(-1, 1),
            "gpu_load_pct": (58 if throttled else 78) + rng.uniform(-5, 5),
            "gpu_clock_mhz": 1900 + rng.uniform(-10, 10),
            "gpu_power_w": 150 + rng.uniform(-10, 10),
            "gpu_fan_rpm": 1500,
            "gpu_vram_used_pct": 63 + rng.uniform(-2, 2),
            "ram_used_pct": 58 + rng.uniform(-1, 1),
        }

    return _assemble(
        "cpu_overheat",
        "Overheating CPU that throttles",
        "The CPU climbs to its thermal limit within a minute, then drops its clock speed. "
        "Frame rate falls with it and the GPU is left waiting. Think: loose cooler, dead pump, "
        "dried paste.",
        [
            "thermal.cpu_hot",
            "thermal.cpu_throttling",
            "performance.cpu_limited",
            "performance.stutter",
        ],
        mode="capture",
        specs=_specs(
            cpu="Intel(R) Core(TM) i7-12700K",
            cores=12,
            board=("ASUSTeK COMPUTER INC.", "PRIME Z690-P"),
        ),
        events=_events(),
        disks=_disks(),
        frames=_frames_csv(
            rng,
            seconds,
            lambda t: 118 if temperature(t) < 93 else 79,
            jitter=0.10,
            spike_every_s=11,
            spike_ms=(40, 85),
            gpu_busy_share=0.62,
        ),
        sensors=_sensors_csv(seconds, sample),
        seconds=seconds,
    )


def stutter_vram(seed: int = 3) -> SampleRun:
    rng = random.Random(seed)
    seconds = 120

    def sample(s: int) -> dict[str, float]:
        return {
            "cpu_temp_c": 66 + rng.uniform(-2, 2),
            "cpu_load_pct": 44 + rng.uniform(-6, 6),
            "cpu_core_max_load_pct": 71 + rng.uniform(-8, 8),
            "cpu_clock_mhz": 4600 + rng.uniform(-40, 40),
            "cpu_power_w": 80 + rng.uniform(-5, 5),
            "gpu_temp_c": 71 + rng.uniform(-1, 1),
            "gpu_hotspot_c": 83 + rng.uniform(-1, 1),
            "gpu_load_pct": 90 + rng.uniform(-6, 6),
            "gpu_clock_mhz": 1890 + rng.uniform(-10, 10),
            "gpu_power_w": 195 + rng.uniform(-10, 10),
            "gpu_fan_rpm": 1750,
            "gpu_vram_used_pct": min(100.0, 98.6 + rng.uniform(-0.8, 0.8)),
            "ram_used_pct": 88 + rng.uniform(-1, 1),
        }

    return _assemble(
        "stutter_vram",
        "Stutter: video memory full, one RAM stick",
        "Average FPS looks fine but the game hitches every few seconds. The 8 GB card's memory "
        "is full and the PC has a single 16 GB stick running at default speed.",
        ["performance.stutter", "gpu.vram_exhausted", "memory.single_channel", "memory.slow_speed"],
        mode="capture",
        specs=_specs(sticks=1, rated=3200, configured=2133, part_numbers=["CMK16GX4M1B3200C16"]),
        events=_events(),
        disks=_disks(),
        frames=_frames_csv(
            rng,
            seconds,
            lambda t: 96 + 5 * math.sin(t / 7),
            jitter=0.09,
            spike_every_s=3.5,
            spike_ms=(55, 190),
            gpu_busy_share=0.88,
        ),
        sensors=_sensors_csv(seconds, sample),
        seconds=seconds,
    )


def whea_bluescreens(seed: int = 4) -> SampleRun:
    events = [
        _event(21.2, "Microsoft-Windows-WHEA-Logger", 18, "Error", WHEA_CPU_FATAL),
        _event(9.4, "Microsoft-Windows-WHEA-Logger", 18, "Error", WHEA_CPU_FATAL),
        _event(2.1, "Microsoft-Windows-WHEA-Logger", 18, "Error", WHEA_CPU_FATAL),
        _bugcheck(21.2, 0x124),
        _bugcheck(9.4, 0x124),
        _bugcheck(2.1, 0x124),
        _event(
            21.2,
            "Microsoft-Windows-Kernel-Power",
            41,
            "Critical",
            KP41,
            BugcheckCode=292,
            PowerButtonTimestamp=0,
        ),
        _event(
            9.4,
            "Microsoft-Windows-Kernel-Power",
            41,
            "Critical",
            KP41,
            BugcheckCode=292,
            PowerButtonTimestamp=0,
        ),
        _event(
            2.1,
            "Microsoft-Windows-Kernel-Power",
            41,
            "Critical",
            KP41,
            BugcheckCode=292,
            PowerButtonTimestamp=0,
        ),
    ]
    return _assemble(
        "whea_bluescreens",
        "Blue screens: WHEA_UNCORRECTABLE_ERROR",
        "Three blue screens in a month, all stop code 0x124, each with a fatal processor-core "
        "error in the event log. Classic unstable overclock/undervolt or a failing CPU.",
        ["hardware.whea_fatal", "stability.bluescreen"],
        mode="quick",
        specs=_specs(
            cpu="Intel(R) Core(TM) i9-13900K",
            cores=24,
            board=("ASUSTeK COMPUTER INC.", "ROG STRIX Z790-E GAMING WIFI"),
            ram_type="DDR5",
            rated=6000,
            configured=6000,
            part_numbers=["F5-6000J3038F16G"] * 2,
        ),
        events=_events(events),
        disks=_disks(),
    )


def failing_disk(seed: int = 5) -> SampleRun:
    disk_message = "The device, \\Device\\Harddisk1\\DR1, has a bad block."
    retry = (
        "The IO operation at logical block address 0x1a2b3c for Disk 1 (PDO name: "
        "\\Device\\00000034) was retried."
    )
    events = [
        *[_event(d, "disk", 7, "Error", disk_message) for d in (14.0, 6.5, 3.2, 0.6)],
        *[_event(d, "disk", 153, "Warning", retry) for d in (15.1, 8.8, 6.6, 3.3, 1.9, 0.7)],
        _event(
            3.2,
            "Ntfs",
            55,
            "Error",
            "A corruption was discovered in the file system structure on volume D:.",
        ),
    ]
    disks = _disks(
        [
            _disk(),
            _disk(
                "ST2000DM008-2FR102",
                media="HDD",
                bus="SATA",
                health="Warning",
                size_gb=1863,
                temp=41,
                wear=None,
                read_bad=38,
                hours=31900,
            ),
        ],
        [_volume("C", 930, 9.4, True), _volume("D", 1862, 640)],
    )
    return _assemble(
        "failing_disk",
        "Failing hard drive and a full Windows drive",
        "A 2 TB hard drive with uncorrectable read errors, bad-block events and file-system "
        "corruption, plus a Windows drive with under 10 GB free.",
        ["storage.disk_unhealthy", "storage.io_errors", "storage.low_space"],
        mode="quick",
        specs=_specs(),
        events=_events(events),
        disks=disks,
    )


def power_loss(seed: int = 6) -> SampleRun:
    events = [
        *[
            _event(
                d,
                "Microsoft-Windows-Kernel-Power",
                41,
                "Critical",
                KP41,
                BugcheckCode=0,
                PowerButtonTimestamp=0,
            )
            for d in (19.0, 11.3, 5.2, 1.4)
        ],
        *[
            _event(
                d,
                "Display",
                4101,
                "Warning",
                "Display driver nvlddmkm stopped responding and has successfully recovered.",
            )
            for d in (11.4, 5.3)
        ],
    ]
    return _assemble(
        "power_loss",
        "Shuts off under load, no blue screen",
        "Four hard power-offs in a month with no stop code, and two graphics driver resets. "
        "The pattern of a power supply that cannot hold the graphics card's load.",
        ["power.unexpected_shutdown", "gpu.driver_timeout"],
        mode="quick",
        specs=_specs(gpu="NVIDIA GeForce RTX 4080 SUPER", vram_gb=16),
        events=_events(events),
        disks=_disks(),
    )


def bad_ram(seed: int = 7) -> SampleRun:
    events = [
        _bugcheck(17.0, 0x1A),
        _bugcheck(12.5, 0x50),
        _bugcheck(8.1, 0x3B),
        _bugcheck(2.0, 0x1A),
        *[
            _event(d, "Microsoft-Windows-WHEA-Logger", 47, "Warning", WHEA_MEMORY_CORRECTED)
            for d in (16.0, 9.9, 4.4, 2.2, 0.9)
        ],
        _event(
            1.0,
            "Microsoft-Windows-MemoryDiagnostics-Results",
            1102,
            "Error",
            "The Windows Memory Diagnostic tested the computer's memory and detected "
            "hardware errors. To identify and repair these problems, contact the computer "
            "manufacturer",
        ),
    ]
    return _assemble(
        "bad_ram",
        "Random blue screens from bad RAM",
        "Different stop codes every time, corrected memory errors, a failed Windows Memory "
        "Diagnostic, and two mismatched sticks.",
        [
            "stability.bluescreen",
            "hardware.whea_corrected",
            "memory.diagnostic_failed",
            "memory.mixed_modules",
        ],
        mode="quick",
        specs=_specs(part_numbers=["F4-3600C16-16GVKC", "CMK16GX4M1B3200C16"]),
        events=_events(events),
        disks=_disks(),
    )


def tired_laptop(seed: int = 8) -> SampleRun:
    events = [
        _event(
            d,
            "Microsoft-Windows-Kernel-Processor-Power",
            37,
            "Warning",
            "The speed of processor 0 in group 0 is being limited by system firmware. The "
            "processor has been in this reduced performance state for 71 seconds since the "
            "last report.",
        )
        for d in (6.0, 3.1, 0.4)
    ]
    return _assemble(
        "tired_laptop",
        "Slow laptop: power saver, worn battery, firmware limit",
        "A three-year-old gaming laptop that 'got slow': Power saver plan, a battery at 52% of "
        "its original capacity, firmware limiting CPU speed, and a 2022 graphics driver.",
        ["os.power_saver_plan", "power.battery_worn", "cpu.firmware_speed_limit", "driver.gpu_old"],
        mode="quick",
        specs=_specs(
            cpu="AMD Ryzen 7 5800H with Radeon Graphics",
            gpu="NVIDIA GeForce RTX 3060 Laptop GPU",
            vram_gb=6,
            driver_date="2022-12-08T00:00:00Z",
            driver_version="31.0.15.2756",
            sticks=2,
            stick_gb=8,
            rated=3200,
            configured=3200,
            part_numbers=["M471A1K43DB1-CWE"] * 2,
            slots=2,
            board=("LENOVO", "LNVNB161216"),
            system_type="laptop",
            power_plan=("Power saver", "a1841308-3541-4fab-bc81-f71556f20b4a"),
            battery={
                "design_capacity_mwh": 80000,
                "full_charge_capacity_mwh": 41600,
                "cycle_count": 612,
                "status": "On AC power",
            },
        ),
        events=_events(events),
        disks=_disks(
            [_disk("SKHynix_HFS512GDE9X081N", size_gb=476, wear=31, hours=9800)],
            [_volume("C", 475, 96, True)],
        ),
    )


SCENARIOS: dict[str, Callable[[], SampleRun]] = {
    "healthy": healthy,
    "cpu_overheat": cpu_overheat,
    "stutter_vram": stutter_vram,
    "whea_bluescreens": whea_bluescreens,
    "failing_disk": failing_disk,
    "power_loss": power_loss,
    "bad_ram": bad_ram,
    "tired_laptop": tired_laptop,
}


def build(name: str) -> SampleRun:
    try:
        return SCENARIOS[name]()
    except KeyError:
        raise KeyError(f"Unknown sample run {name!r}. Known: {', '.join(SCENARIOS)}") from None


def build_all() -> list[SampleRun]:
    return [factory() for factory in SCENARIOS.values()]
