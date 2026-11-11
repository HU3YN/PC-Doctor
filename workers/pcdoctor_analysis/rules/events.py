"""Rules that read the Windows event log.

Event ids, levels and message texts were dumped from a real Windows machine
(docs/verified-facts.md). Where a provider has no machine-readable definition
(disk, storahci, stornvme, Display), the ids are the long-documented ones.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from ..loader import RunData
from ..model import Finding, Severity, Thresholds
from ..stopcodes import STOP_CODES, format_code, parse_code
from . import rule

WHEA = "Microsoft-Windows-WHEA-Logger"
KERNEL_POWER = "Microsoft-Windows-Kernel-Power"
WER = "Microsoft-Windows-WER-SystemErrorReporting"
MEMDIAG = "Microsoft-Windows-MemoryDiagnostics-Results"
PROCESSOR_POWER = "Microsoft-Windows-Kernel-Processor-Power"


def _times(events: list[dict[str, Any]]) -> tuple[str, str]:
    stamps = sorted(str(e.get("time", "")) for e in events if e.get("time"))
    return (stamps[0], stamps[-1]) if stamps else ("", "")


def _window(run: RunData) -> str:
    days = run.event_window_days
    return f"the last {days} days" if days else "the collected period"


# ------------------------------------------------------------------- WHEA

_COMPONENT = re.compile(r"(?:Reported by component|Component):\s*([^\r\n]+)", re.IGNORECASE)
_ERROR_TYPE = re.compile(r"Error Type:\s*([^\r\n]+)", re.IGNORECASE)

# Where to look, by the component Windows names in the event.
_WHEA_ADVICE: dict[str, tuple[str, list[str]]] = {
    "processor": (
        "cpu",
        [
            "Reset the BIOS to defaults: remove any overclock, undervolt or curve optimizer.",
            "Update the BIOS - it carries CPU microcode fixes.",
            "Check CPU temperature under load and the cooler mounting.",
            "If errors continue at stock settings, test with another power supply, then "
            "suspect the CPU or motherboard.",
        ],
    ),
    "memory": (
        "memory",
        [
            "Run MemTest86 or Windows Memory Diagnostic for at least one full pass.",
            "Turn XMP/EXPO off and retest; if the errors stop, the profile is not stable.",
            "Test one stick at a time to find the bad module or slot.",
        ],
    ),
    "pci": (
        "motherboard",
        [
            "Reseat the graphics card and any NVMe drives or add-in cards.",
            "If a PCIe riser cable is used, replace it or set the slot to an older PCIe "
            "generation in the BIOS.",
            "Update the chipset driver and the BIOS.",
            "Look at the Bus:Device:Function in the event to see which device it is.",
        ],
    ),
}


# WHEA-Logger event ids, from the provider's own definitions on Windows
# (docs/verified-facts.md). Using the id first keeps this working on a
# non-English Windows, where the message text is translated.
WHEA_FATAL_IDS = frozenset({1, 16, 18, 20, 22, 24, 26, 29, 40, 42, 44, 46, 48})
WHEA_CORRECTED_IDS = frozenset({2, 17, 19, 21, 23, 25, 27, 28, 41, 43, 45, 47, 49})
_WHEA_COMPONENT_BY_ID: dict[int, str] = {
    **dict.fromkeys((18, 19, 28, 29), "Processor Core"),
    **dict.fromkeys((20, 21), "AMD Northbridge"),
    **dict.fromkeys((22, 23, 46, 47, 48, 49), "Memory"),
    **dict.fromkeys((24, 25, 42, 43), "PCI/PCI-X Bus"),
    **dict.fromkeys((26, 27, 44, 45), "PCI/PCI-X Device"),
}


def _whea_component(event: dict[str, Any]) -> str:
    known = _WHEA_COMPONENT_BY_ID.get(event.get("id"))  # type: ignore[arg-type]
    if known:
        return known
    # Ids 16, 17, 40 and 41 name the component only in the message text.
    match = _COMPONENT.search(str(event.get("message", "")))
    return match.group(1).strip() if match else "Unknown component"


def _whea_advice(components: Counter[str]) -> tuple[str, list[str]]:
    top = components.most_common(1)[0][0].lower() if components else ""
    for key, advice in _WHEA_ADVICE.items():
        if key in top:
            return advice
    return (
        "motherboard",
        [
            "Open the event in Event Viewer: the details name the component and error source.",
            "Reset the BIOS to defaults and update it.",
            "Check temperatures and test with a known-good power supply.",
        ],
    )


def _is_corrected(event: dict[str, Any]) -> bool:
    event_id = event.get("id")
    if event_id in WHEA_CORRECTED_IDS:
        return True
    if event_id in WHEA_FATAL_IDS:
        return False
    # An id this list does not know: fall back to the wording, then the level.
    message = str(event.get("message", "")).lower()
    if "corrected" in message:
        return True
    if "fatal" in message:
        return False
    return str(event.get("level", "")).lower() in ("warning", "information")


def _whea_summary(events: list[dict[str, Any]]) -> tuple[Counter[str], Counter[str], list[str]]:
    components: Counter[str] = Counter()
    types: Counter[str] = Counter()
    ids: list[str] = []
    for event in events:
        message = str(event.get("message", ""))
        components[_whea_component(event)] += 1
        match = _ERROR_TYPE.search(message)
        if match:
            types[match.group(1).strip()] += 1
        code = f"WHEA-{event.get('id')}"
        if code not in ids:
            ids.append(code)
    return components, types, ids


def _counter_text(counter: Counter[str]) -> str:
    return ", ".join(f"{name} ({count})" for name, count in counter.most_common(4))


@rule(
    "hardware.whea_fatal",
    "cpu",
    "Fatal hardware errors (WHEA)",
    "The hardware reported an error it could not recover from.",
    "the Windows event log",
)
def whea_fatal(run: RunData, t: Thresholds) -> list[Finding] | None:
    if not run.events_collected:
        return None
    events = [e for e in run.events_from(WHEA) if not _is_corrected(e)]
    # Id 3 is an informational record, not an error.
    events = [e for e in events if e.get("id") != 3]
    if not events:
        return []
    components, types, ids = _whea_summary(events)
    category, checks = _whea_advice(components)
    first, last = _times(events)
    summary = (
        f"Windows logged {len(events)} fatal hardware error(s) in {_window(run)}, reported by: "
        f"{_counter_text(components)}. "
    )
    if types:
        summary += f"Error type: {_counter_text(types)}. "
    summary += (
        "These come from the hardware itself, not from Windows or a program, and usually go "
        "with a blue screen (WHEA_UNCORRECTABLE_ERROR) or a sudden restart."
    )
    return [
        Finding(
            code="hardware.whea_fatal",
            category=category,
            severity=Severity.CRITICAL,
            title=f"{len(events)} fatal hardware error(s): {components.most_common(1)[0][0]}",
            summary=summary,
            next_checks=checks,
            evidence={
                "count": len(events),
                "components": dict(components),
                "error_types": dict(types),
                "first": first,
                "last": last,
            },
            error_codes=ids,
        )
    ]


@rule(
    "hardware.whea_corrected",
    "cpu",
    "Corrected hardware errors (WHEA)",
    "The hardware keeps making errors that it manages to correct - an early warning.",
    "the Windows event log",
)
def whea_corrected(run: RunData, t: Thresholds) -> list[Finding] | None:
    if not run.events_collected:
        return None
    events = [e for e in run.events_from(WHEA) if _is_corrected(e) and e.get("id") != 3]
    if len(events) < t.whea_corrected_warn:
        return []
    components, types, ids = _whea_summary(events)
    category, checks = _whea_advice(components)
    first, last = _times(events)
    summary = (
        f"Windows logged {len(events)} corrected hardware error(s) in {_window(run)}, reported "
        f"by: {_counter_text(components)}. "
    )
    if types:
        summary += f"Error type: {_counter_text(types)}. "
    summary += (
        "Each one was caught and fixed, so nothing crashed - but healthy hardware does not "
        "produce these. They are often the first sign of an unstable overclock or undervolt, "
        "marginal RAM, or a bad PCIe connection, and they can turn into crashes."
    )
    return [
        Finding(
            code="hardware.whea_corrected",
            category=category,
            severity=Severity.WARNING,
            title=f"{len(events)} corrected hardware error(s): {components.most_common(1)[0][0]}",
            summary=summary,
            next_checks=checks,
            evidence={
                "count": len(events),
                "components": dict(components),
                "error_types": dict(types),
                "first": first,
                "last": last,
            },
            error_codes=ids,
        )
    ]


# -------------------------------------------------------- shutdowns, crashes


def _data(event: dict[str, Any]) -> dict[str, Any]:
    data = event.get("data")
    return data if isinstance(data, dict) else {}


def _int(value: Any) -> int | None:
    """Event data arrives as text: '0', '292', sometimes '0x124'."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(text, 16) if text.lower().startswith("0x") else int(text)
        except ValueError:
            return None
    return None


@rule(
    "power.unexpected_shutdown",
    "power",
    "Unexpected shutdowns",
    "The PC lost power or froze and was forced off, without a blue screen.",
    "the Windows event log",
)
def unexpected_shutdown(run: RunData, t: Thresholds) -> list[Finding] | None:
    if not run.events_collected:
        return None
    events = run.events_from(KERNEL_POWER, (41,))
    # A Kernel-Power 41 with a bug check code is a blue screen; the blue-screen
    # rule reports those. This rule is for the ones with no code at all.
    silent = [e for e in events if not _int(_data(e).get("BugcheckCode"))]
    if not silent:
        return []
    button = sum(
        1
        for e in silent
        if _int(_data(e).get("PowerButtonTimestamp"))
        or str(_data(e).get("LongPowerButtonPressDetected", "")).lower() == "true"
    )
    first, last = _times(silent)
    count = len(silent)
    summary = (
        f"The PC went down without shutting down cleanly {count} time(s) in {_window(run)} "
        "(Kernel-Power event 41 with no stop code). Windows had no chance to record why, which "
        "means the power was cut or the machine froze solid - it did not blue-screen."
    )
    if button:
        summary += (
            f" In {button} of them the power button was held down, so the PC had hung and was "
            "forced off."
        )
    checks = [
        "Ask what was happening each time: under load (gaming) points at the power supply or "
        "heat; at idle points at sleep states, RAM or the board.",
        "Check the power supply: wattage against the GPU, age, and that every modular cable "
        "is fully seated at both ends. Swap in a known-good PSU if you can.",
        "Check CPU and GPU temperatures under load - an overheat cut-off looks exactly like this.",
        "Check the wall side: power strip, UPS, loose kettle lead.",
        "Reset the BIOS to defaults (no overclock, no undervolt) and retest.",
    ]
    return [
        Finding(
            code="power.unexpected_shutdown",
            category="power",
            severity=Severity.CRITICAL
            if count >= t.unexpected_shutdowns_crit
            else Severity.WARNING,
            title=f"{count} unexpected shutdown(s) with no stop code",
            summary=summary,
            next_checks=checks,
            evidence={
                "count": count,
                "power_button_held": button,
                "first": first,
                "last": last,
            },
            error_codes=["Kernel-Power-41"],
        )
    ]


_BUGCHECK_IN_TEXT = re.compile(r"bugcheck was:\s*(0x[0-9A-Fa-f]{1,8})", re.IGNORECASE)


def _bugcheck_code(event: dict[str, Any]) -> int | None:
    data = _data(event)
    # BugCheck events: param1 is "0x00000124 (0x..., 0x..., 0x..., 0x...)".
    param = data.get("param1")
    if param not in (None, ""):
        code = parse_code(str(param).split("(")[0])
        if code:
            return code
    # Kernel-Power stores the stop code as a decimal number.
    code = _int(data.get("BugcheckCode"))
    if code:
        return code
    match = _BUGCHECK_IN_TEXT.search(str(event.get("message", "")))
    return int(match.group(1), 16) if match else None


@rule(
    "stability.bluescreen",
    "os",
    "Blue screens",
    "Windows crashed with a stop code (blue screen).",
    "the Windows event log",
)
def bluescreen(run: RunData, t: Thresholds) -> list[Finding] | None:
    if not run.events_collected:
        return None
    wer = run.events_from(WER, (1000, 1001, 1006))
    drivers = Counter(
        str(_data(e).get("SuspectedDriver", "")).strip()
        for e in run.events_from(WER, (1019,))
        if str(_data(e).get("SuspectedDriver", "")).strip()
    )
    codes: Counter[int] = Counter()
    unknown = 0
    source = wer
    if wer:
        for event in wer:
            code = _bugcheck_code(event)
            if code:
                codes[code] += 1
            else:
                unknown += 1
    else:
        # No BugCheck events (they are skipped when the dump cannot be written),
        # so fall back to the stop code Kernel-Power 41 carries.
        source = [
            e for e in run.events_from(KERNEL_POWER, (41,)) if _int(_data(e).get("BugcheckCode"))
        ]
        for event in source:
            codes[_int(_data(event).get("BugcheckCode")) or 0] += 1
    total = sum(codes.values()) + unknown
    if total == 0:
        return []

    lines = []
    hardware = False
    for code, count in codes.most_common():
        entry = STOP_CODES.get(code)
        times = f"{count}x " if count > 1 else ""
        if entry:
            hardware = hardware or entry.hardware_likely
            meaning = f" - {entry.meaning}" if entry.meaning else ""
            lines.append(f"{times}{entry.hex} {entry.name}{meaning}")
        else:
            lines.append(f"{times}{format_code(code)} (not in the built-in list)")
    if unknown:
        lines.append(f"{unknown} crash(es) where Windows did not record the stop code")

    top = STOP_CODES.get(codes.most_common(1)[0][0]) if codes else None
    category = top.category if top and top.category != "other" else "os"
    checks = list(top.checks) if top and top.checks else []
    if drivers:
        named = ", ".join(f"{name} ({count})" for name, count in drivers.most_common(3))
        checks.insert(0, f"Windows named a possibly related driver: {named}. Start there.")
    if len(codes) >= 3:
        checks.insert(
            0,
            "Several different stop codes usually means hardware (RAM first, then CPU and "
            "power), not one bad driver.",
        )
    if not checks:
        checks = [
            "Look the stop code up and check the driver named on the blue screen.",
            "Test the RAM and check disk health.",
        ]
    checks.append("The minidumps in C:\\Windows\\Minidump name the failing driver (WinDbg).")

    first, last = _times(source)
    severe = total >= t.bluescreens_crit or hardware
    summary = f"Windows blue-screened {total} time(s) in {_window(run)}: " + "; ".join(lines) + "."
    if top and top.causes:
        summary += " Usual causes, most likely first: " + "; ".join(top.causes) + "."
    return [
        Finding(
            code="stability.bluescreen",
            category=category,
            severity=Severity.CRITICAL if severe else Severity.WARNING,
            title=(
                f"{total} blue screen(s): "
                + (f"{top.hex} {top.name}" if top else "stop code not recorded")
                + (f" and {len(codes) - 1} other code(s)" if len(codes) > 1 else "")
            ),
            summary=summary,
            next_checks=checks,
            evidence={
                "count": total,
                "codes": {format_code(c): n for c, n in codes.most_common()},
                "suspected_drivers": dict(drivers),
                "first": first,
                "last": last,
            },
            error_codes=[format_code(c) for c, _ in codes.most_common()],
        )
    ]


# ------------------------------------------------------------ other events


@rule(
    "gpu.driver_timeout",
    "gpu",
    "Graphics driver resets",
    "The graphics driver stopped responding and Windows restarted it.",
    "the Windows event log",
)
def gpu_driver_timeout(run: RunData, t: Thresholds) -> list[Finding] | None:
    if not run.events_collected:
        return None
    events = run.events_from("Display", (4101,))
    if len(events) < t.display_driver_resets_warn:
        return []
    first, last = _times(events)
    return [
        Finding(
            code="gpu.driver_timeout",
            category="gpu",
            severity=Severity.WARNING,
            title=f"Graphics driver stopped responding {len(events)} time(s)",
            summary=(
                f"The display driver hung and was restarted {len(events)} time(s) in "
                f"{_window(run)} (Display event 4101). The user sees a black screen for a "
                "second, a frozen game, or a crash to desktop. One or two after a driver update "
                "can be nothing; a pattern points at the card, its power or its cooling."
            ),
            next_checks=[
                "Clean-install the graphics driver (DDU in Safe Mode, then the current driver).",
                "Remove any GPU overclock or undervolt.",
                "Check GPU temperature under load and reseat the card and its power cables - "
                "use separate PCIe cables, not one daisy-chained cable.",
                "Check the power supply is big enough for the card.",
                "Test the card in another PC, or another card in this one.",
            ],
            evidence={"count": len(events), "first": first, "last": last},
            error_codes=["Display-4101"],
        )
    ]


# provider (lower case) -> {event id: (what it means, is it serious)}
_STORAGE_EVENTS: dict[str, dict[int, tuple[str, bool]]] = {
    "disk": {
        7: ("a bad block on the disk", True),
        11: ("a controller error", False),
        51: ("an error during a paging operation", False),
        52: ("the drive predicting its own failure", True),
        153: ("an I/O operation that had to be retried", False),
    },
    "storahci": {129: ("a reset sent to a drive that stopped answering", False)},
    "stornvme": {
        11: ("a controller error", False),
        129: ("a reset sent to a drive that stopped answering", False),
    },
    "ntfs": {55: ("file system corruption", True)},
    "microsoft-windows-ntfs": {55: ("file system corruption", True)},
}


@rule(
    "storage.io_errors",
    "storage",
    "Disk and file-system errors",
    "Windows logged bad blocks, drive resets, I/O retries or file-system corruption.",
    "the Windows event log",
)
def storage_io_errors(run: RunData, t: Thresholds) -> list[Finding] | None:
    if not run.events_collected:
        return None
    counts: Counter[str] = Counter()
    codes: list[str] = []
    matched: list[dict[str, Any]] = []
    serious = False
    for event in run.events:
        provider = str(event.get("provider", "")).lower()
        known = _STORAGE_EVENTS.get(provider, {}).get(event.get("id"))  # type: ignore[arg-type]
        if not known:
            continue
        meaning, is_serious = known
        counts[meaning] += 1
        serious = serious or is_serious
        matched.append(event)
        label = "Ntfs" if "ntfs" in provider else provider
        code = f"{label}-{event.get('id')}"
        if code not in codes:
            codes.append(code)
    if not matched:
        return []
    first, last = _times(matched)
    detail = "; ".join(f"{count}x {meaning}" for meaning, count in counts.most_common())
    return [
        Finding(
            code="storage.io_errors",
            category="storage",
            severity=Severity.CRITICAL if serious else Severity.WARNING,
            title=f"{len(matched)} disk error event(s) in the event log",
            summary=(
                f"Windows logged storage errors in {_window(run)}: {detail}. "
                + (
                    "Bad blocks, failure predictions and file-system corruption mean data is "
                    "at risk now."
                    if serious
                    else "Resets and retries mean a drive stopped answering for a moment - a "
                    "failing drive, a bad cable or port, or a power problem. They also cause "
                    "long freezes in games."
                )
            ),
            next_checks=[
                "Back up anything important before testing further.",
                "Check the drive's health and reliability counters (see the disk findings).",
                "Replace the SATA cable or move the drive to another port or M.2 slot.",
                "Update the SSD firmware and the storage controller driver.",
                "Run 'chkdsk /scan' on the affected volume.",
            ],
            evidence={"count": len(matched), "by_kind": dict(counts), "first": first, "last": last},
            error_codes=codes,
        )
    ]


@rule(
    "memory.diagnostic_failed",
    "memory",
    "Windows Memory Diagnostic result",
    "Windows Memory Diagnostic found bad memory.",
    "a Windows Memory Diagnostic result in the event log",
)
def memory_diagnostic_failed(run: RunData, t: Thresholds) -> list[Finding] | None:
    if not run.events_collected:
        return None
    results = run.events_from(MEMDIAG, (1101, 1102, 1201, 1202))
    if not results:
        return None  # the test has not been run in the collected period
    failed = [e for e in results if e.get("id") in (1102, 1202)]
    if not failed:
        return []
    _, last = _times(failed)
    return [
        Finding(
            code="memory.diagnostic_failed",
            category="memory",
            severity=Severity.CRITICAL,
            title="Windows Memory Diagnostic detected hardware errors",
            summary=(
                "Windows Memory Diagnostic tested the RAM and found errors. That test does not "
                "produce false alarms: at least one memory module, or the slot or settings it "
                "runs with, is bad. Random crashes, corrupt files and failed installs follow."
            ),
            next_checks=[
                "Turn XMP/EXPO off and run the test again - if it passes, the profile is not "
                "stable on this board.",
                "Test one stick at a time, in the slot the board manual lists first, to find "
                "the bad module.",
                "Test the good stick in each slot to rule out a bad slot.",
                "Replace the faulty module (RAM is usually under lifetime warranty).",
            ],
            evidence={"failed_results": len(failed), "last": last},
            error_codes=[f"MemoryDiagnostics-{failed[-1].get('id')}"],
        )
    ]


@rule(
    "cpu.firmware_speed_limit",
    "cpu",
    "CPU speed limited by firmware",
    "The firmware is holding the processor below full speed.",
    "the Windows event log",
)
def firmware_speed_limit(run: RunData, t: Thresholds) -> list[Finding] | None:
    if not run.events_collected:
        return None
    events = run.events_from(PROCESSOR_POWER, (37,))
    if not events:
        return []
    first, last = _times(events)
    return [
        Finding(
            code="cpu.firmware_speed_limit",
            category="cpu",
            severity=Severity.WARNING,
            title=f"Firmware limited the CPU's speed ({len(events)} event(s))",
            summary=(
                f"Windows logged {len(events)} event(s) in {_window(run)} saying the processor's "
                "speed is being limited by system firmware (Kernel-Processor-Power event 37). "
                "The BIOS or embedded controller is holding the CPU back - on a laptop usually "
                "because of heat, a weak or third-party charger, or a worn battery; on a desktop "
                "because of a power or temperature limit in the BIOS."
            ),
            next_checks=[
                "Check CPU temperatures and clean the cooling.",
                "On a laptop: use the original charger at its full wattage and check battery "
                "health.",
                "Update the BIOS and check its power and thermal limit settings.",
            ],
            evidence={"count": len(events), "first": first, "last": last},
            error_codes=["Kernel-Processor-Power-37"],
        )
    ]
