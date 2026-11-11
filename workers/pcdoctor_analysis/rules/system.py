"""Rules about how the PC is set up: RAM layout and speed, drivers, power plan,
battery, and memory that fills up during the run."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..loader import RunData, parse_time
from ..model import Finding, Severity, Thresholds
from ..presentmon import percentile
from . import rule

INBOX_DRIVER_DATE = (2006, 6, 21)
POWER_SAVER_GUID = "a1841308-3541-4fab-bc81-f71556f20b4a"
# Speeds a kit runs at when no XMP/EXPO profile is loaded (JEDEC defaults).
DEFAULT_SPEEDS = {"DDR4": 2666, "DDR5": 4800}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return None


# What firmware writes when nobody filled a field in.
_PLACEHOLDERS = frozenset(
    {"", "none", "unknown", "n/a", "default string", "to be filled by o.e.m.", "not specified"}
)
_VM_MARKERS = ("virtual", "vmware", "qemu", "kvm", "xen", "parallels", "bochs")


def _real(value: Any) -> str:
    """The text, or "" when it is a firmware placeholder like "None"."""
    text = str(value or "").strip()
    return "" if text.lower() in _PLACEHOLDERS else text


def is_virtual_machine(run: RunData) -> bool:
    system = run.specs.get("system") if run.specs else None
    if not isinstance(system, dict):
        return False
    text = f"{system.get('manufacturer') or ''} {system.get('model') or ''}".lower()
    return any(marker in text for marker in _VM_MARKERS)


def _modules(run: RunData) -> list[dict[str, Any]]:
    # A virtual machine's "memory modules" are whatever the hypervisor made
    # up (Hyper-V shows 1 GB + 7 GB), so RAM layout rules do not apply.
    if is_virtual_machine(run):
        return []
    memory = run.specs.get("memory") if run.specs else None
    modules = memory.get("modules", []) if isinstance(memory, dict) else []
    return [m for m in modules if (_number(m.get("capacity_bytes")) or 0) > 0]


def _is_laptop(run: RunData) -> bool:
    system = run.specs.get("system") if run.specs else None
    return isinstance(system, dict) and str(system.get("type", "")).lower() == "laptop"


@rule(
    "memory.single_channel",
    "memory",
    "RAM channel layout",
    "Only one memory module is fitted, so the RAM runs in single-channel mode.",
    "memory modules from the collector",
)
def single_channel(run: RunData, t: Thresholds) -> list[Finding] | None:
    modules = _modules(run)
    if not modules:
        return None
    if len(modules) != 1:
        return []
    memory = run.specs.get("memory", {})
    slots = _number(memory.get("slots_total"))
    if slots is not None and slots < 2:
        return []  # nothing the owner can do about a one-slot machine
    size_gb = (_number(modules[0].get("capacity_bytes")) or 0) / 1024**3
    laptop = _is_laptop(run)
    return [
        Finding(
            code="memory.single_channel",
            category="memory",
            severity=Severity.INFO if laptop else Severity.WARNING,
            title=f"Single-channel RAM: one {size_gb:.0f} GB stick",
            summary=(
                f"Only one memory module is fitted ({size_gb:.0f} GB), so the RAM runs in "
                "single-channel mode with half the memory bandwidth. In games this mainly "
                "hurts the lows: the average FPS drops a little, the 1% lows and stutter get "
                "noticeably worse - most of all with integrated graphics."
                + (
                    " Some laptops also have memory soldered to the board that Windows does "
                    "not list as a module."
                    if laptop
                    else ""
                )
            ),
            next_checks=[
                "Add a matching second stick (same capacity and speed).",
                "Fit the pair in the slots the motherboard manual names for two sticks - "
                "usually the 2nd and 4th from the CPU.",
            ],
            evidence={"modules": 1, "slots_total": slots, "capacity_gb": round(size_gb, 1)},
        )
    ]


@rule(
    "memory.slow_speed",
    "memory",
    "RAM speed (XMP / EXPO)",
    "The RAM runs slower than it is rated for - the XMP/EXPO profile is probably off.",
    "memory module speeds from the collector",
)
def slow_speed(run: RunData, t: Thresholds) -> list[Finding] | None:
    modules = [m for m in _modules(run) if (_number(m.get("configured_speed_mhz")) or 0) > 0]
    if not modules:
        return None
    configured = min(_number(m.get("configured_speed_mhz")) or 0 for m in modules)
    rated = max((_number(m.get("speed_mhz")) or 0) for m in modules)
    kind = str(modules[0].get("type") or "").upper()

    below_rated = rated > 0 and configured < rated * 0.9
    at_default = (
        kind in DEFAULT_SPEEDS and configured <= DEFAULT_SPEEDS[kind] and not _is_laptop(run)
    )
    if not (below_rated or at_default):
        return []
    if below_rated:
        title = f"RAM runs at {configured:.0f} MHz but is rated for {rated:.0f} MHz"
        summary = (
            f"The memory is rated for {rated:.0f} MHz but is running at {configured:.0f} MHz. "
            "That almost always means the XMP (Intel) or EXPO/DOCP (AMD) profile is switched "
            "off in the BIOS, which is the default after a new build or a BIOS reset. The PC "
            "is stable like this but leaves free performance unused, mostly in CPU-limited "
            "games."
        )
    else:
        title = f"RAM runs at the default {configured:.0f} MHz"
        summary = (
            f"The {kind} memory is running at {configured:.0f} MHz, the speed a kit falls back "
            "to when no XMP/EXPO profile is loaded. If the kit is a faster one (check the "
            "sticker on the stick), the profile is switched off in the BIOS. If the sticker "
            "also says this speed, nothing is wrong."
        )
    return [
        Finding(
            code="memory.slow_speed",
            category="memory",
            severity=Severity.INFO,
            title=title,
            summary=summary,
            next_checks=[
                "Enter the BIOS and turn on XMP / EXPO / DOCP (profile 1).",
                "Check the result in Task Manager > Performance > Memory > Speed.",
                "If the PC becomes unstable afterwards, update the BIOS, or the kit is not "
                "stable at its rated speed on this board.",
            ],
            evidence={
                "configured_speed_mhz": configured,
                "rated_speed_mhz": rated or None,
                "type": kind or None,
            },
        )
    ]


@rule(
    "memory.mixed_modules",
    "memory",
    "Matching RAM modules",
    "The memory modules are different sizes or different models.",
    "memory modules from the collector",
)
def mixed_modules(run: RunData, t: Thresholds) -> list[Finding] | None:
    modules = _modules(run)
    if not modules:
        return None
    if len(modules) < 2:
        return []
    sizes = {int(_number(m.get("capacity_bytes")) or 0) for m in modules}
    parts = {_real(m.get("part_number")) for m in modules}
    parts.discard("")
    if len(sizes) <= 1 and len(parts) <= 1:
        return []
    described = ", ".join(
        f"{(_number(m.get('capacity_bytes')) or 0) / 1024**3:.0f} GB "
        f"{_real(m.get('part_number')) or 'unknown part'}"
        for m in modules
    )
    return [
        Finding(
            code="memory.mixed_modules",
            category="memory",
            severity=Severity.INFO,
            title="Mixed RAM modules",
            summary=(
                f"The memory modules do not match: {described}. Mixed kits often work, but they "
                "are a common cause of crashes that only appear with XMP/EXPO on, and unequal "
                "sizes leave part of the memory in single-channel mode."
            ),
            next_checks=[
                "If the PC is unstable, test with one matched pair only.",
                "For an upgrade, replace all sticks with one matched kit rather than adding to "
                "an old one.",
            ],
            evidence={"modules": len(modules), "part_numbers": sorted(parts)},
        )
    ]


def _p95(values: list[float]) -> float:
    return percentile(sorted(values), 95)


@rule(
    "memory.ram_exhausted",
    "memory",
    "RAM usage during the run",
    "The PC ran out of free memory during the run.",
    "RAM usage from sensors",
)
def ram_exhausted(run: RunData, t: Thresholds) -> list[Finding] | None:
    if run.sensors is None or not run.sensors.has("ram_used_pct", 10):
        return None
    used = _p95(run.sensors.values("ram_used_pct"))
    if used < t.ram_used_warn_pct:
        return []
    total = _number((run.specs.get("memory") or {}).get("total_bytes")) if run.specs else None
    total_text = f" of {total / 1024**3:.0f} GB" if total else ""
    return [
        Finding(
            code="memory.ram_exhausted",
            category="memory",
            severity=Severity.WARNING,
            title=f"RAM was full during the run ({used:.0f}% used)",
            summary=(
                f"Memory use reached {used:.0f}%{total_text}. With no free RAM, Windows moves "
                "data to the page file on the drive, which is thousands of times slower - the "
                "classic cause of long hitches and stutter that gets worse the longer you play."
            ),
            next_checks=[
                "Close browsers and background apps before gaming and retest.",
                "Check Task Manager > Processes sorted by Memory for anything unusual "
                "(a leak grows over time).",
                "Add RAM: 16 GB is the practical minimum for current games, 32 GB is comfortable.",
            ],
            evidence={"ram_used_p95_pct": round(used, 1), "total_bytes": total},
        )
    ]


@rule(
    "gpu.vram_exhausted",
    "gpu",
    "Video memory usage during the run",
    "The graphics card ran out of video memory during the run.",
    "VRAM usage from sensors",
)
def vram_exhausted(run: RunData, t: Thresholds) -> list[Finding] | None:
    if run.sensors is None or not run.sensors.has("gpu_vram_used_pct", 10):
        return None
    used = _p95(run.sensors.values("gpu_vram_used_pct"))
    if used < t.vram_used_warn_pct:
        return []
    return [
        Finding(
            code="gpu.vram_exhausted",
            category="gpu",
            severity=Severity.WARNING,
            title=f"Video memory was full during the run ({used:.0f}% used)",
            summary=(
                f"The graphics card's memory was {used:.0f}% full. When VRAM runs out the game "
                "has to swap textures in and out through system RAM, which causes sudden "
                "stutter, texture pop-in and large FPS drops - even when the GPU itself is fast "
                "enough."
            ),
            next_checks=[
                "Lower texture quality first - it is the biggest VRAM user and costs little FPS.",
                "Lower resolution or turn off ray tracing and frame generation.",
                "Close other GPU users (browser, second monitor video, overlays).",
            ],
            evidence={"vram_used_p95_pct": round(used, 1)},
        )
    ]


def _gpus(run: RunData) -> list[dict[str, Any]]:
    gpus = run.specs.get("gpu", []) if run.specs else []
    return [g for g in gpus if isinstance(g, dict) and str(g.get("name") or "").strip()]


@rule(
    "driver.gpu_missing",
    "driver",
    "Graphics driver installed",
    "No real graphics driver is installed (Microsoft Basic Display Adapter).",
    "graphics adapters from the collector",
)
def gpu_driver_missing(run: RunData, t: Thresholds) -> list[Finding] | None:
    gpus = _gpus(run)
    if not gpus:
        return None
    basic = [g for g in gpus if "basic display" in str(g.get("name", "")).lower()]
    if not basic:
        return []
    return [
        Finding(
            code="driver.gpu_missing",
            category="driver",
            severity=Severity.WARNING,
            title="No graphics driver installed (Microsoft Basic Display Adapter)",
            summary=(
                "Windows is using its built-in fallback display driver. There is no 3D "
                "acceleration, the resolution and refresh rate are limited, and games will not "
                "run properly. This is normal straight after installing Windows, and it is "
                "also what a failing graphics card can fall back to."
            ),
            next_checks=[
                "Install the current driver from NVIDIA, AMD or Intel.",
                "If the driver will not install or the device shows an error in Device Manager "
                "(Code 43), reseat the card and test it in another PC.",
            ],
            evidence={"adapters": [str(g.get("name")) for g in gpus]},
        )
    ]


@rule(
    "driver.gpu_old",
    "driver",
    "Graphics driver age",
    "The graphics driver is old.",
    "graphics driver dates from the collector",
)
def gpu_driver_old(run: RunData, t: Thresholds) -> list[Finding] | None:
    dated = []
    for gpu in _gpus(run):
        # Every driver that ships inside Windows is dated 2006-06-21, whatever
        # its real age (Microsoft does this so a vendor driver always wins).
        # That date says nothing, so those drivers are not judged.
        if str(gpu.get("name", "")).lower().startswith("microsoft"):
            continue
        when = parse_time(gpu.get("driver_date"))
        if when and (when.year, when.month, when.day) != INBOX_DRIVER_DATE:
            dated.append((gpu, when))
    if not dated:
        return None
    now = run.captured_at or datetime.now(UTC)
    findings: list[Finding] = []
    for gpu, when in dated:
        months = (now.year - when.year) * 12 + (now.month - when.month)
        if months < t.gpu_driver_old_months:
            continue
        findings.append(
            Finding(
                code="driver.gpu_old",
                category="driver",
                severity=Severity.INFO,
                title=f"Graphics driver is {months} months old: {gpu.get('name')}",
                summary=(
                    f"The driver for {gpu.get('name')} is dated {when.date().isoformat()} "
                    f"(version {gpu.get('driver_version') or 'unknown'}). Newer games may run "
                    "slower or crash on a driver this old. It is not a fault by itself - and on "
                    "a stable machine that only runs older software, leaving it is reasonable."
                ),
                next_checks=[
                    "Install the current driver from the GPU maker.",
                    "If problems started after an update instead, roll back one version.",
                ],
                evidence={
                    "gpu": gpu.get("name"),
                    "driver_version": gpu.get("driver_version"),
                    "driver_date": when.date().isoformat(),
                    "age_months": months,
                },
            )
        )
    return findings


@rule(
    "os.power_saver_plan",
    "os",
    "Windows power plan",
    "Windows is set to the Power saver plan, which caps CPU speed.",
    "the active power plan from the collector",
)
def power_saver_plan(run: RunData, t: Thresholds) -> list[Finding] | None:
    guid = str(run.specs.get("power_plan_guid") or "").strip().lower() if run.specs else ""
    name = str(run.specs.get("power_plan") or "").strip() if run.specs else ""
    if not guid and not name:
        return None
    if guid != POWER_SAVER_GUID and "power saver" not in name.lower():
        return []
    return [
        Finding(
            code="os.power_saver_plan",
            category="os",
            severity=Severity.WARNING,
            title="Windows is on the Power saver plan",
            summary=(
                "The active power plan is Power saver. It holds the processor at low clock "
                "speeds to save energy, so the PC feels slow and games lose a lot of FPS even "
                "though nothing is broken."
            ),
            next_checks=[
                "Switch to Balanced (or High performance): Control Panel > Power Options.",
                "On a laptop, plug in the charger and set Settings > System > Power > Power "
                "mode to Best performance.",
            ],
            evidence={"power_plan": name or None, "power_plan_guid": guid or None},
        )
    ]


@rule(
    "power.battery_worn",
    "power",
    "Laptop battery health",
    "The laptop battery has lost a large part of its capacity.",
    "battery capacities from the collector",
)
def battery_worn(run: RunData, t: Thresholds) -> list[Finding] | None:
    battery = run.specs.get("battery") if run.specs else None
    if not isinstance(battery, dict):
        return None
    design = _number(battery.get("design_capacity_mwh"))
    full = _number(battery.get("full_charge_capacity_mwh"))
    if not design or full is None or design <= 0:
        return None
    lost = max(0.0, 1.0 - full / design) * 100.0
    if lost < t.battery_wear_warn_pct:
        return []
    return [
        Finding(
            code="power.battery_worn",
            category="power",
            severity=Severity.WARNING,
            title=f"Battery has lost {lost:.0f}% of its capacity",
            summary=(
                f"The battery now holds {full / 1000:.1f} Wh against {design / 1000:.1f} Wh when "
                f"new - {lost:.0f}% of its capacity is gone. Expect short run time, sudden "
                "shut-offs under load, and on some laptops reduced CPU speed on battery."
            ),
            next_checks=[
                "Replace the battery.",
                "Check for swelling: a lifted trackpad or a case that no longer closes flat "
                "means stop using it and replace it now.",
            ],
            evidence={
                "design_capacity_mwh": design,
                "full_charge_capacity_mwh": full,
                "capacity_lost_pct": round(lost, 1),
                "cycle_count": battery.get("cycle_count"),
            },
        )
    ]
