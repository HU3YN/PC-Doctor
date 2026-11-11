"""Temperature and throttling rules."""

from __future__ import annotations

from statistics import median

from ..loader import RunData
from ..model import Finding, Severity, Thresholds
from ..sensors import SensorData
from . import rule

COOLING_CHECKS = [
    "Check that every fan spins and the cooler is firmly mounted (a loose or tilted cooler "
    "is the most common cause after a build or a move).",
    "Blow dust out of the heatsink, radiator and filters.",
    "Replace the thermal paste if the build is more than a few years old.",
    "Check case airflow: intake and exhaust fans pointing the right way, nothing blocking them.",
]


@rule(
    "thermal.cpu_hot",
    "thermal",
    "CPU temperature",
    "The processor runs too hot under load.",
    "CPU temperature from sensors",
)
def cpu_hot(run: RunData, t: Thresholds) -> list[Finding] | None:
    sensors = run.sensors
    if sensors is None or not sensors.has("cpu_temp_c"):
        return None
    temps = sensors.values("cpu_temp_c")
    peak = max(temps)
    hot_share = sum(1 for v in temps if v >= t.cpu_temp_sustained_c) / len(temps)
    sustained = hot_share >= t.cpu_temp_sustained_share
    if peak < t.cpu_temp_warn_c and not sustained:
        return []
    critical = peak >= t.cpu_temp_crit_c
    summary = (
        f"The CPU peaked at {peak:.0f} °C and spent {hot_share:.0%} of the run at "
        f"{t.cpu_temp_sustained_c:.0f} °C or hotter. "
    )
    if critical:
        summary += (
            "That is at the processor's thermal limit: it protects itself by slowing down, and "
            "may shut the PC off."
        )
    else:
        summary += (
            "That is hotter than a healthy cooling setup should allow, and close to where the "
            "processor starts slowing itself down."
        )
    summary += (
        " Some recent CPUs (Ryzen 7000 and newer, high-end Core i7/i9) are designed to run "
        "into the 90s under an all-core load, so judge this together with the throttling check."
    )
    return [
        Finding(
            code="thermal.cpu_hot",
            category="thermal",
            severity=Severity.CRITICAL if critical else Severity.WARNING,
            title=f"CPU running hot: peak {peak:.0f} °C",
            summary=summary,
            next_checks=COOLING_CHECKS
            + [
                "If it is an AIO liquid cooler: listen for the pump and feel both tubes - one "
                "hot and one cold means no flow."
            ],
            evidence={
                "cpu_temp_max_c": round(peak, 1),
                "cpu_temp_avg_c": round(sum(temps) / len(temps), 1),
                "share_of_run_hot": round(hot_share, 3),
                "hot_line_c": t.cpu_temp_sustained_c,
            },
        )
    ]


def _clock_drop(
    sensors: SensorData,
    temp_column: str,
    clock_column: str,
    load_column: str,
    hot_c: float,
    cool_c: float,
    min_load: float,
    min_samples: int,
) -> tuple[float, float, int] | None:
    """Median clock while hot and while cooler, both under load.

    Returns (hot clock, cool clock, hot sample count), or None when the run
    does not contain enough of both to compare.
    """
    temps = sensors.series.get(temp_column, [])
    clocks = sensors.series.get(clock_column, [])
    loads = sensors.series.get(load_column, [])
    hot: list[float] = []
    cool: list[float] = []
    for i, temp in enumerate(temps):
        clock = clocks[i] if i < len(clocks) else None
        if temp is None or clock is None:
            continue
        if loads:
            load = loads[i] if i < len(loads) else None
            if load is None or load < min_load:
                continue  # an idle CPU clocks down on its own; that is not throttling
        if temp >= hot_c:
            hot.append(clock)
        elif temp < cool_c:
            cool.append(clock)
    if len(hot) < min_samples or len(cool) < min_samples:
        return None
    return median(hot), median(cool), len(hot)


@rule(
    "thermal.cpu_throttling",
    "thermal",
    "CPU thermal throttling",
    "The processor slows itself down when it gets hot.",
    "CPU temperature and CPU clock speed from sensors",
)
def cpu_throttling(run: RunData, t: Thresholds) -> list[Finding] | None:
    sensors = run.sensors
    if sensors is None or not sensors.has("cpu_temp_c", t.throttle_min_samples * 2):
        return None
    clock_column = next(
        (
            c
            for c in ("cpu_clock_mhz", "cpu_perf_pct")
            if sensors.has(c, t.throttle_min_samples * 2)
        ),
        None,
    )
    if clock_column is None:
        return None
    result = _clock_drop(
        sensors,
        "cpu_temp_c",
        clock_column,
        "cpu_load_pct",
        t.throttle_hot_c,
        t.throttle_cool_c,
        t.throttle_min_load_pct,
        t.throttle_min_samples,
    )
    if result is None:
        return []  # never hot, or never cool: nothing to compare
    hot_clock, cool_clock, hot_samples = result
    if cool_clock <= 0:
        return []
    drop = 1.0 - hot_clock / cool_clock
    if drop < t.throttle_clock_drop:
        return []
    unit = "MHz" if clock_column == "cpu_clock_mhz" else "% of rated speed"
    return [
        Finding(
            code="thermal.cpu_throttling",
            category="thermal",
            severity=Severity.WARNING,
            title=f"CPU is thermal throttling: {drop:.0%} slower when hot",
            summary=(
                f"Under load the CPU ran at about {cool_clock:.0f} {unit} while below "
                f"{t.throttle_cool_c:.0f} °C, but dropped to about {hot_clock:.0f} {unit} once it "
                f"reached {t.throttle_hot_c:.0f} °C. It is slowing itself down to stop the "
                "temperature rising, which costs performance and causes uneven frame times."
            ),
            next_checks=COOLING_CHECKS
            + [
                "On a laptop: clean the fans, check the vents are clear, and repaste if it is "
                "more than a couple of years old."
            ],
            evidence={
                "clock_when_cool": round(cool_clock, 1),
                "clock_when_hot": round(hot_clock, 1),
                "clock_unit": unit,
                "drop": round(drop, 3),
                "hot_samples": hot_samples,
            },
        )
    ]


@rule(
    "thermal.gpu_hot",
    "thermal",
    "GPU temperature",
    "The graphics card runs too hot under load.",
    "GPU temperature from sensors",
)
def gpu_hot(run: RunData, t: Thresholds) -> list[Finding] | None:
    sensors = run.sensors
    if sensors is None or not (sensors.has("gpu_temp_c") or sensors.has("gpu_hotspot_c")):
        return None
    core = max(sensors.values("gpu_temp_c"), default=None)
    hotspot = max(sensors.values("gpu_hotspot_c"), default=None)
    core_warn = core is not None and core >= t.gpu_temp_warn_c
    spot_warn = hotspot is not None and hotspot >= t.gpu_hotspot_warn_c
    if not (core_warn or spot_warn):
        return []
    critical = (core is not None and core >= t.gpu_temp_crit_c) or (
        hotspot is not None and hotspot >= t.gpu_hotspot_crit_c
    )
    readings = []
    if core is not None:
        readings.append(f"core peaked at {core:.0f} °C")
    if hotspot is not None:
        readings.append(f"hot spot peaked at {hotspot:.0f} °C")
    evidence = {}
    if core is not None:
        evidence["gpu_temp_max_c"] = round(core, 1)
    if hotspot is not None:
        evidence["gpu_hotspot_max_c"] = round(hotspot, 1)
    fans = sensors.values("gpu_fan_rpm")
    if fans:
        evidence["gpu_fan_max_rpm"] = round(max(fans))
    title_temp = core if core is not None else hotspot
    return [
        Finding(
            code="thermal.gpu_hot",
            category="thermal",
            severity=Severity.CRITICAL if critical else Severity.WARNING,
            title=f"GPU running hot: peak {title_temp:.0f} °C",
            summary=(
                f"The graphics card's {' and its '.join(readings)}. Most cards start cutting "
                "clock speed in the mid-80s, and running this hot for long shortens the life of "
                "the fans and thermal pads. A hot spot far above the core temperature points at "
                "dried paste or a poorly seated cooler."
            ),
            next_checks=[
                "Check that all the card's fans spin up under load.",
                "Blow dust out of the card's heatsink and the case filters.",
                "Give the card air: clear the slots below it, add or fix case intake fans.",
                "On an older card, replace the thermal paste and pads.",
                "Use a more aggressive fan curve (the vendor tool or the card's BIOS switch).",
            ],
            evidence=evidence,
        )
    ]


@rule(
    "thermal.gpu_throttling",
    "thermal",
    "GPU thermal throttling",
    "The graphics card cuts its clock speed when it gets hot.",
    "GPU temperature, clock speed and load from sensors",
)
def gpu_throttling(run: RunData, t: Thresholds) -> list[Finding] | None:
    sensors = run.sensors
    needed = ("gpu_temp_c", "gpu_clock_mhz", "gpu_load_pct")
    if sensors is None or not all(sensors.has(c, t.throttle_min_samples * 2) for c in needed):
        return None
    result = _clock_drop(
        sensors,
        "gpu_temp_c",
        "gpu_clock_mhz",
        "gpu_load_pct",
        t.gpu_throttle_hot_c,
        t.gpu_throttle_cool_c,
        t.gpu_throttle_min_load_pct,
        t.throttle_min_samples,
    )
    if result is None:
        return []
    hot_clock, cool_clock, hot_samples = result
    if cool_clock <= 0:
        return []
    drop = 1.0 - hot_clock / cool_clock
    if drop < t.throttle_clock_drop:
        return []
    return [
        Finding(
            code="thermal.gpu_throttling",
            category="thermal",
            severity=Severity.WARNING,
            title=f"GPU is thermal throttling: clock {drop:.0%} lower when hot",
            summary=(
                f"At full load the graphics card ran at about {cool_clock:.0f} MHz while below "
                f"{t.gpu_throttle_cool_c:.0f} °C but only about {hot_clock:.0f} MHz at "
                f"{t.gpu_throttle_hot_c:.0f} °C and above. It is giving up performance to keep "
                "its temperature down."
            ),
            next_checks=[
                "Fix the GPU cooling first - see the GPU temperature finding.",
                "Check case airflow and the card's fan curve.",
            ],
            evidence={
                "clock_when_cool_mhz": round(cool_clock),
                "clock_when_hot_mhz": round(hot_clock),
                "drop": round(drop, 3),
                "hot_samples": hot_samples,
            },
        )
    ]


@rule(
    "thermal.shutdown",
    "thermal",
    "Thermal shutdowns",
    "Windows shut the PC down because a temperature sensor hit its critical limit.",
    "the Windows event log",
)
def thermal_shutdown(run: RunData, t: Thresholds) -> list[Finding] | None:
    if not run.events_collected:
        return None
    events = run.events_from("Microsoft-Windows-Kernel-Power", (86,))
    if not events:
        return []
    times = sorted(str(e.get("time", "")) for e in events)
    return [
        Finding(
            code="thermal.shutdown",
            category="thermal",
            severity=Severity.CRITICAL,
            title=f"Windows shut down for overheating {len(events)} time(s)",
            summary=(
                f"The event log records {len(events)} shutdown(s) caused by a critical thermal "
                "event (Kernel-Power event 86). The firmware reported a temperature past its "
                "safe limit and Windows powered off to protect the hardware."
            ),
            next_checks=COOLING_CHECKS + ["Do not keep stress-testing until the cooling is fixed."],
            evidence={"count": len(events), "last": times[-1]},
            error_codes=["Kernel-Power-86"],
        )
    ]
