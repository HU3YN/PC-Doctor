"""Frame-time and bottleneck rules."""

from __future__ import annotations

from statistics import median

from ..loader import RunData
from ..model import Finding, Severity, Thresholds
from ..presentmon import compute_frame_stats
from . import rule


@rule(
    "performance.stutter",
    "performance",
    "Frame-time stutter",
    "Uneven frame times: spikes, hitches, or 1% lows far below the average.",
    "a PresentMon capture",
)
def stutter(run: RunData, t: Thresholds) -> list[Finding] | None:
    if run.frames is None:
        return None
    stats = compute_frame_stats(run.frames, t)
    if not stats.enough_frames:
        return None
    many_spikes = stats.spikes_per_min >= t.stutter_spikes_per_min_warn
    poor_lows = stats.low_ratio < t.stutter_low_ratio_warn and stats.avg_fps >= 20
    if not (many_spikes or poor_lows):
        return []

    parts = [
        f"Average {stats.avg_fps:.0f} FPS, but the slowest 1% of frames ran at "
        f"{stats.fps_1pct_low:.0f} FPS."
    ]
    if stats.spike_count:
        parts.append(
            f"{stats.spike_count} frames took more than twice as long as the frames around "
            f"them ({stats.spikes_per_min:.1f} per minute)."
        )
    if stats.hitch_count:
        parts.append(
            f"{stats.hitch_count} of those were hitches of {t.hitch_ms:.0f} ms or more; "
            f"the worst frame took {stats.frame_time_max_ms:.0f} ms."
        )
    parts.append("That is what the player feels as stutter, even when the FPS counter looks fine.")

    checks = [
        "Look at the other findings first: full RAM or VRAM, overheating, a single RAM stick "
        "and a busy CPU all cause stutter.",
        "Close background apps (browsers, launchers, RGB and monitoring tools) and retest.",
        "Check whether it is one game only: shader compilation stutter is the game, not the PC.",
        "Make sure the game is on an SSD and the drive is healthy and not nearly full.",
        "Update the GPU driver and chipset driver; turn XMP/EXPO on if RAM runs at default speed.",
    ]
    return [
        Finding(
            code="performance.stutter",
            category="performance",
            severity=Severity.WARNING,
            title=f"Stutter: 1% low is {stats.fps_1pct_low:.0f} FPS against "
            f"{stats.avg_fps:.0f} FPS average",
            summary=" ".join(parts),
            next_checks=checks,
            evidence={
                "application": stats.application,
                "avg_fps": round(stats.avg_fps, 1),
                "fps_1pct_low": round(stats.fps_1pct_low, 1),
                "fps_01pct_low": round(stats.fps_01pct_low, 1),
                "spike_count": stats.spike_count,
                "spikes_per_min": round(stats.spikes_per_min, 2),
                "hitch_count": stats.hitch_count,
                "worst_frame_ms": round(stats.frame_time_max_ms, 1),
            },
        )
    ]


def idle_capture(run: RunData, t: Thresholds) -> float | None:
    """The median GPU load when a capture caught an idle PC (no frame times and
    the graphics card barely used), else None. The owner's first real capture
    was like this: 3% GPU load for five minutes, and both "limited" checks
    claimed to have passed."""
    if run.frames is not None or not (run.sensors and run.sensors.has("gpu_load_pct", 10)):
        return None
    load = median(run.sensors.values("gpu_load_pct"))
    return load if load < t.idle_gpu_load_pct else None


def _gpu_load(run: RunData) -> float | None:
    """Typical GPU load during the run (median), from sensors or PresentMon."""
    if run.sensors and run.sensors.has("gpu_load_pct", 10):
        return median(run.sensors.values("gpu_load_pct"))
    if run.frames is not None and run.frames.gpu_busy_ms:
        share = compute_frame_stats(run.frames).gpu_busy_share
        return share * 100.0 if share is not None else None
    return None


@rule(
    "performance.gpu_limited",
    "performance",
    "GPU-limited performance",
    "The graphics card is the limit on frame rate (normal in most games).",
    "GPU load from sensors, or GPU busy time from PresentMon",
)
def gpu_limited(run: RunData, t: Thresholds) -> list[Finding] | None:
    if idle_capture(run, t) is not None:
        return None  # nothing was being played: no verdict either way
    load = _gpu_load(run)
    if load is None:
        return None
    if load < t.gpu_limited_load_pct:
        return []
    return [
        Finding(
            code="performance.gpu_limited",
            category="performance",
            severity=Severity.INFO,
            title=f"GPU-limited: the graphics card ran at {load:.0f}% load",
            summary=(
                f"The graphics card was working flat out ({load:.0f}% load for most of the run), "
                "so it sets the frame rate. This is the normal, healthy state in a demanding game "
                "- it is not a fault."
            ),
            next_checks=[
                "For more FPS: lower resolution or render scale, shadows, ray tracing; or turn "
                "on DLSS / FSR / XeSS.",
                "A faster CPU or more RAM will not raise the frame rate here.",
            ],
            evidence={"gpu_load_median_pct": round(load, 1)},
        )
    ]


@rule(
    "performance.cpu_limited",
    "performance",
    "CPU-limited performance",
    "The processor is the limit on frame rate while the graphics card waits.",
    "GPU and CPU load from sensors",
)
def cpu_limited(run: RunData, t: Thresholds) -> list[Finding] | None:
    sensors = run.sensors
    if sensors is None or not sensors.has("gpu_load_pct", 10):
        return None
    if idle_capture(run, t) is not None:
        return None  # nothing was being played: no verdict either way
    has_core = sensors.has("cpu_core_max_load_pct", 10)
    if not has_core and not sensors.has("cpu_load_pct", 10):
        return None
    gpu = median(sensors.values("gpu_load_pct"))
    column = "cpu_core_max_load_pct" if has_core else "cpu_load_pct"
    cpu = median(sensors.values(column))
    if gpu >= t.cpu_limited_gpu_load_below_pct or cpu < t.cpu_limited_core_load_pct:
        return []
    what = "busiest CPU core" if has_core else "CPU"
    return [
        Finding(
            code="performance.cpu_limited",
            category="performance",
            severity=Severity.INFO,
            title=f"CPU-limited: GPU at {gpu:.0f}% while the {what} sat at {cpu:.0f}%",
            summary=(
                f"The graphics card had headroom ({gpu:.0f}% load) while the {what} was at "
                f"{cpu:.0f}%. The processor could not prepare frames fast enough, so the GPU "
                "waited. A CPU limit usually shows as lower FPS than the GPU could deliver and "
                "more stutter."
            ),
            next_checks=[
                "Check RAM first: turn on XMP/EXPO and use two sticks - slow or single-channel "
                "RAM makes a CPU limit much worse.",
                "Close background programs and check for thermal throttling on the CPU.",
                "Lower CPU-heavy settings (crowd density, view distance, physics) or raise "
                "resolution - raising resolution costs nothing while the CPU is the limit.",
                "If the CPU is old for the graphics card, a CPU upgrade is the real fix.",
            ],
            evidence={
                "gpu_load_median_pct": round(gpu, 1),
                f"{column}_median": round(cpu, 1),
            },
        )
    ]
