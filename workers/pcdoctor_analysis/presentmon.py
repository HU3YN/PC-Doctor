"""Read a PresentMon CSV and compute frame-time statistics.

PresentMon has renamed its columns across versions, so nothing here depends on
one exact header. The names below were read from PresentMon's own source
(CsvOutput.cpp) and its flags were run for real against 2.6.0 on Windows; see
docs/verified-facts.md.

    output mode              frame time           timestamp         GPU busy
    default (2.x, current)   MsBetweenPresents    TimeInSeconds     MsGPUBusy
    --v2_metrics             FrameTime            CPUStartTime      GPUBusy
    --v1_metrics and 1.x     msBetweenPresents    TimeInSeconds     msGPUActive

Lookup is case-insensitive, and the first name that exists wins.
"""

from __future__ import annotations

import csv
import io
from bisect import bisect_left, insort
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .model import Thresholds

FRAME_TIME_COLUMNS = ("msbetweenpresents", "frametime")
TIME_COLUMNS = (
    "timeinseconds",
    "cpustarttimeinseconds",
    "cpustarttime",
    "timeinms",
    "cpustarttimeinms",
)
GPU_BUSY_COLUMNS = ("msgpubusy", "gpubusy", "msgpuactive")
CPU_BUSY_COLUMNS = ("mscpubusy", "cpubusy")
DISPLAYED_COLUMNS = ("displayedtime", "msuntildisplayed")
DROPPED_COLUMNS = ("dropped",)

# Windows shell processes that present frames but are never the thing being
# tested. Compared case-insensitively.
SHELL_PROCESSES = frozenset(
    {
        "dwm.exe",
        "explorer.exe",
        "searchhost.exe",
        "searchapp.exe",
        "shellexperiencehost.exe",
        "startmenuexperiencehost.exe",
        "textinputhost.exe",
        "applicationframehost.exe",
        "systemsettings.exe",
        "lockapp.exe",
        "widgets.exe",
        "taskmgr.exe",
        "presentmon.exe",
    }
)

LEVEL_SHIFT_FRAMES = 3
MAX_ROWS = 2_000_000  # ~2.3 hours at 240 fps; a guard, not a real limit


class PresentMonError(ValueError):
    """The file is not a usable PresentMon capture."""


@dataclass
class FrameData:
    """Frame times of the one process (and swap chain) that was measured."""

    application: str
    frame_times_ms: list[float]
    elapsed_s: list[float]  # time of each frame since the first one
    gpu_busy_ms: list[float] | None = None
    cpu_busy_ms: list[float] | None = None
    dropped_frames: int | None = None
    other_applications: int = 0  # how many other presenting processes were in the file
    notes: list[str] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        return sum(self.frame_times_ms) / 1000.0


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if not value or value.upper() == "NA":
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if number != number or number in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return number


def _pick(header: dict[str, str], candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        if name in header:
            return header[name]
    return None


def parse_presentmon_csv(
    source: str | Path | io.TextIOBase,
    target_process: str | None = None,
) -> FrameData:
    """Parse a PresentMon CSV.

    ``target_process`` is the process to analyse (for example ``game.exe``).
    Without it, the process that presented the most frames is used, ignoring
    Windows shell processes.
    """
    if isinstance(source, (str, Path)):
        # utf-8-sig strips the byte-order mark PowerShell likes to add.
        with open(source, newline="", encoding="utf-8-sig", errors="replace") as handle:
            return _parse(handle, target_process)
    return _parse(source, target_process)


def _parse(handle: Any, target_process: str | None) -> FrameData:
    reader = csv.reader(handle)
    try:
        raw_header = next(reader)
    except StopIteration:
        raise PresentMonError("The PresentMon file is empty.") from None

    header = {name.strip().lower(): name.strip() for name in raw_header}
    index = {name.strip().lower(): i for i, name in enumerate(raw_header)}

    ft_name = _pick(header, FRAME_TIME_COLUMNS)
    if ft_name is None:
        raise PresentMonError(
            "No frame-time column found (expected MsBetweenPresents or FrameTime). "
            f"Columns in the file: {', '.join(raw_header[:12])}"
        )

    def col(candidates: tuple[str, ...]) -> int | None:
        name = _pick(header, candidates)
        return index[name.lower()] if name else None

    i_ft = index[ft_name.lower()]
    i_app = index.get("application")
    i_pid = index.get("processid")
    i_swap = index.get("swapchainaddress")
    i_time = col(TIME_COLUMNS)
    i_gpu = col(GPU_BUSY_COLUMNS)
    i_cpu = col(CPU_BUSY_COLUMNS)
    i_disp = col(DISPLAYED_COLUMNS)
    i_drop = col(DROPPED_COLUMNS)

    # One pass: keep the rows, grouped by (application, pid, swap chain).
    groups: dict[tuple[str, str, str], list[list[str]]] = {}
    count = 0
    for row in reader:
        if not row or len(row) <= i_ft:
            continue
        count += 1
        if count > MAX_ROWS:
            raise PresentMonError(f"The PresentMon file has more than {MAX_ROWS:,} rows.")
        key = (
            row[i_app].strip() if i_app is not None and i_app < len(row) else "",
            row[i_pid].strip() if i_pid is not None and i_pid < len(row) else "",
            row[i_swap].strip() if i_swap is not None and i_swap < len(row) else "",
        )
        groups.setdefault(key, []).append(row)

    if not groups:
        raise PresentMonError(
            "The PresentMon file has a header but no frames. Nothing was presenting "
            "during the capture - was the game running?"
        )

    frames_per_app: Counter[str] = Counter()
    for (app, _pid, _swap), rows in groups.items():
        frames_per_app[app] += len(rows)

    notes: list[str] = []
    chosen_app = _choose_application(frames_per_app, target_process, notes)

    # Within the chosen process, use its busiest swap chain so frames from two
    # windows are never interleaved.
    candidates = {k: v for k, v in groups.items() if k[0] == chosen_app}
    best_key = max(candidates, key=lambda k: len(candidates[k]))
    if len(candidates) > 1:
        notes.append(
            f"{chosen_app} had {len(candidates)} swap chains or instances; "
            "the busiest one was analysed."
        )
    rows = candidates[best_key]

    frame_times: list[float] = []
    times: list[float | None] = []
    gpu_busy: list[float] = []
    cpu_busy: list[float] = []
    dropped = 0
    dropped_known = i_disp is not None or i_drop is not None
    skipped = 0

    for row in rows:
        ft = _to_float(row[i_ft])
        if ft is None or ft <= 0:
            skipped += 1  # the first frame of a capture has no previous present
            continue
        frame_times.append(ft)
        times.append(_to_float(row[i_time]) if i_time is not None and i_time < len(row) else None)
        if i_gpu is not None and i_gpu < len(row):
            gpu_busy.append(_to_float(row[i_gpu]) or 0.0)
        if i_cpu is not None and i_cpu < len(row):
            cpu_busy.append(_to_float(row[i_cpu]) or 0.0)
        if i_drop is not None and i_drop < len(row):
            if row[i_drop].strip() == "1":
                dropped += 1
        elif i_disp is not None and i_disp < len(row) and row[i_disp].strip().upper() == "NA":
            dropped += 1

    if not frame_times:
        raise PresentMonError(f"No valid frame times for {chosen_app or 'the capture'}.")
    if skipped > 1:
        notes.append(f"{skipped} rows without a usable frame time were skipped.")

    return FrameData(
        application=chosen_app,
        frame_times_ms=frame_times,
        elapsed_s=_elapsed_seconds(frame_times, times),
        gpu_busy_ms=gpu_busy if len(gpu_busy) == len(frame_times) else None,
        cpu_busy_ms=cpu_busy if len(cpu_busy) == len(frame_times) else None,
        dropped_frames=dropped if dropped_known else None,
        other_applications=len(frames_per_app) - 1,
        notes=notes,
    )


def _choose_application(
    frames_per_app: Counter[str], target_process: str | None, notes: list[str]
) -> str:
    if target_process:
        wanted = target_process.strip().lower()
        for app in frames_per_app:
            if app.lower() == wanted or app.lower() == wanted + ".exe":
                return app
        notes.append(
            f"The target process {target_process} is not in the capture; "
            "the busiest process was analysed instead."
        )
    real = {a: n for a, n in frames_per_app.items() if a.lower() not in SHELL_PROCESSES}
    pool = real or dict(frames_per_app)
    if not real:
        notes.append("Only Windows shell processes were captured - no game was presenting.")
    return max(pool, key=lambda a: pool[a])


def _elapsed_seconds(frame_times_ms: list[float], times: list[float | None]) -> list[float]:
    """Elapsed time of each frame, in seconds from the first frame.

    The timestamp column is used only when it is complete, increasing, and
    agrees with the frame times (as seconds or as milliseconds). Otherwise the
    frame times are summed, which is always self-consistent.
    """
    total_s = sum(frame_times_ms) / 1000.0
    n = len(frame_times_ms)
    if n >= 2 and all(t is not None for t in times):
        ts = [t for t in times if t is not None]
        span = ts[-1] - ts[0]
        monotonic = all(b >= a for a, b in zip(ts, ts[1:], strict=False))
        if monotonic and span > 0:
            expected = total_s - frame_times_ms[0] / 1000.0
            for scale in (1.0, 0.001):  # column in seconds, or in milliseconds
                if expected > 0 and abs(span * scale - expected) <= 0.2 * expected + 0.05:
                    start = ts[0]
                    return [(t - start) * scale for t in ts]
    elapsed: list[float] = []
    running = 0.0
    for ft in frame_times_ms:
        elapsed.append(running)
        running += ft / 1000.0
    return elapsed


# --------------------------------------------------------------------- stats


def percentile(sorted_values: list[float], pct: float) -> float:
    """Percentile with linear interpolation. ``sorted_values`` must be sorted."""
    if not sorted_values:
        raise ValueError("percentile of an empty list")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * (pct / 100.0)
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    fraction = position - low
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * fraction


def find_spikes(frame_times_ms: list[float], thresholds: Thresholds) -> list[int]:
    """Indexes of frames that are spikes.

    A frame is a spike when it took more than ``spike_ratio`` times the median
    of the previous ``spike_window_frames`` frames and at least
    ``spike_min_extra_ms`` longer than that median. Comparing with the recent
    median (not the whole run) means a slow scene is not a spike, but a single
    long frame in a smooth scene is.

    A spike is left out of the window, so one long frame does not hide the
    next. But when ``LEVEL_SHIFT_FRAMES`` frames in a row are all "spikes",
    the game has simply become slower (a new scene, a throttling CPU): the
    first of them is kept as the spike and the window restarts at the new
    level. A burst of long frames therefore counts as one stutter event.
    """
    window = thresholds.spike_window_frames
    warmup = min(window, 10)
    spikes: list[int] = []
    recent: deque[float] = deque()  # the window, in arrival order
    ordered: list[float] = []  # the same frames, kept sorted for the median
    streak = 0  # consecutive spikes so far

    def push(value: float) -> None:
        recent.append(value)
        insort(ordered, value)
        if len(recent) > window:
            del ordered[bisect_left(ordered, recent.popleft())]

    for i, ft in enumerate(frame_times_ms):
        size = len(recent)
        is_spike = False
        if size >= warmup:
            middle = size // 2
            median = ordered[middle] if size % 2 else (ordered[middle - 1] + ordered[middle]) / 2
            is_spike = (
                ft > median * thresholds.spike_ratio
                and ft - median >= thresholds.spike_min_extra_ms
            )
        if not is_spike:
            streak = 0
            push(ft)
            continue
        streak += 1
        spikes.append(i)
        if streak >= LEVEL_SHIFT_FRAMES:
            # Not spikes after all, apart from the first: a new, slower level.
            del spikes[-(streak - 1) :]
            recent.clear()
            ordered.clear()
            for value in frame_times_ms[i - streak + 1 : i + 1]:
                push(value)
            streak = 0
    return spikes


@dataclass
class FrameStats:
    application: str
    frames: int
    duration_s: float
    avg_fps: float
    median_fps: float
    fps_1pct_low: float  # average FPS of the slowest 1% of frames
    fps_01pct_low: float  # average FPS of the slowest 0.1% of frames
    fps_p1: float  # FPS at the 99th-percentile frame time
    frame_time_avg_ms: float
    frame_time_median_ms: float
    frame_time_p95_ms: float
    frame_time_p99_ms: float
    frame_time_max_ms: float
    spike_count: int
    spikes_per_min: float
    hitch_count: int  # spikes of at least Thresholds.hitch_ms
    low_ratio: float  # fps_1pct_low / avg_fps; 1.0 is perfectly even
    dropped_frames: int | None
    gpu_busy_share: float | None  # share of frame time the GPU was working
    cpu_busy_share: float | None
    enough_frames: bool  # False = too short to trust the percentiles

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in self.__dict__.items():
            out[key] = round(value, 3) if isinstance(value, float) else value
        return out


def _low_average_fps(sorted_desc: list[float], share: float) -> float:
    """Average FPS over the slowest ``share`` of frames (at least one frame)."""
    count = max(1, int(len(sorted_desc) * share))
    slowest = sorted_desc[:count]
    return 1000.0 * len(slowest) / sum(slowest)


def compute_frame_stats(data: FrameData, thresholds: Thresholds | None = None) -> FrameStats:
    thresholds = thresholds or Thresholds()
    ft = data.frame_times_ms
    n = len(ft)
    total_ms = sum(ft)
    ordered = sorted(ft)
    descending = ordered[::-1]
    spikes = find_spikes(ft, thresholds)
    hitches = sum(1 for i in spikes if ft[i] >= thresholds.hitch_ms)
    duration_s = total_ms / 1000.0
    avg_fps = 1000.0 * n / total_ms
    median = percentile(ordered, 50)
    low_1 = _low_average_fps(descending, 0.01)

    def share(busy: list[float] | None) -> float | None:
        if not busy or total_ms <= 0:
            return None
        return min(1.0, sum(busy) / total_ms)

    return FrameStats(
        application=data.application,
        frames=n,
        duration_s=duration_s,
        avg_fps=avg_fps,
        median_fps=1000.0 / median,
        fps_1pct_low=low_1,
        fps_01pct_low=_low_average_fps(descending, 0.001),
        fps_p1=1000.0 / percentile(ordered, 99),
        frame_time_avg_ms=total_ms / n,
        frame_time_median_ms=median,
        frame_time_p95_ms=percentile(ordered, 95),
        frame_time_p99_ms=percentile(ordered, 99),
        frame_time_max_ms=ordered[-1],
        spike_count=len(spikes),
        spikes_per_min=len(spikes) / (duration_s / 60.0) if duration_s > 0 else 0.0,
        hitch_count=hitches,
        low_ratio=low_1 / avg_fps if avg_fps > 0 else 0.0,
        dropped_frames=data.dropped_frames,
        gpu_busy_share=share(data.gpu_busy_ms),
        cpu_busy_share=share(data.cpu_busy_ms),
        enough_frames=n >= thresholds.min_frames_for_stats,
    )
