"""Demo data: synthetic runs and made-up work-log entries.

Lets someone see the whole dashboard working before they have captured
anything. Every demo row is flagged is_demo and can be removed in one click.
None of it is real: no real machine, no real customer, no real measurement.
"""

from __future__ import annotations

from datetime import date, timedelta

from pcdoctor_analysis import synth
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Run, WorkLogEntry
from .ingest import delete_run, ingest

# (days ago, fields). Written the way real notes look: short and specific.
DEMO_ENTRIES: list[tuple[int, dict]] = [
    (
        41,
        dict(
            title="Random restarts under load, no blue screen",
            status="fixed",
            category="power",
            device_type="gaming_pc",
            device="Ryzen 7 5800X / RTX 3080 / 650 W PSU",
            symptoms="PC cuts out to black and reboots a few minutes into any game. No stop code, "
            "nothing on screen. Fine at the desktop.",
            steps="Event log: Kernel-Power 41 with BugcheckCode 0, several per day. Temps normal "
            "(CPU 74, GPU 71). RAM passed one MemTest pass. Swapped in a bench 850 W PSU: "
            "two hours of load, no restart.",
            root_cause="650 W power supply could not hold the RTX 3080's transient spikes. GPU was "
            "also on one daisy-chained PCIe cable.",
            fix="Replaced with an 850 W Gold unit and ran two separate PCIe cables to the card.",
            components=["RTX 3080", "650W PSU"],
            error_codes=["Kernel-Power-41"],
            minutes_spent=95,
        ),
    ),
    (
        33,
        dict(
            title="WHEA_UNCORRECTABLE_ERROR blue screens after new build",
            status="fixed",
            category="cpu",
            device_type="gaming_pc",
            device="Core i9-13900K / Z790 / 32 GB DDR5-6000",
            symptoms="Blue screen 0x124 two or three times a week, mostly while compiling shaders "
            "or under all-core load.",
            steps="WHEA-Logger event 18, Processor Core, Cache Hierarchy Error, different APIC "
            "IDs. "
            "BIOS was on the board's 'unlimited' power profile. CPU hit 100 C in Cinebench.",
            root_cause="Motherboard default removed Intel's power limits; CPU unstable at that "
            "voltage and heat. BIOS was also a year old (old microcode).",
            fix="Updated BIOS, enabled the Intel default power profile (253 W), reseated the AIO "
            "cold plate. Stable through 3 hours of load, peak 88 C.",
            components=["i9-13900K", "Z790"],
            error_codes=["0x124", "WHEA-18"],
            minutes_spent=120,
        ),
    ),
    (
        26,
        dict(
            title="Stutter every few seconds in new games",
            status="fixed",
            category="memory",
            device_type="gaming_pc",
            device="Ryzen 5 5600 / RTX 3060 / 1x16 GB DDR4",
            symptoms="Average FPS fine but constant hitching. Customer already reinstalled Windows "
            "and the GPU driver.",
            steps="One 16 GB stick in slot A1, running at 2133 MHz. Task Manager showed 92% memory "
            "in use while gaming. Frame-time capture: 1% low under a third of the average.",
            root_cause="Single-channel RAM at default speed, and not enough of it.",
            fix="Fitted a matched 2x16 GB 3600 kit in A2/B2 and enabled XMP. 1% lows roughly "
            "doubled, hitching gone.",
            components=["Ryzen 5 5600", "RTX 3060", "DDR4"],
            minutes_spent=40,
        ),
    ),
    (
        19,
        dict(
            title="Black screen flashes, 'display driver stopped responding'",
            status="fixed",
            category="gpu",
            device_type="gaming_pc",
            device="Core i5-12400F / RTX 3070",
            symptoms="Screen goes black for a second mid-game, sometimes crashes to desktop. "
            "Started after moving the PC.",
            steps="Event log full of Display 4101 (nvlddmkm). DDU and clean driver made no "
            "difference. GPU sagging visibly; one of two 8-pin plugs not fully clicked in.",
            root_cause="GPU power connector partly unseated and card sagging in the slot after the "
            "move.",
            fix="Reseated the card and both power plugs, added a support bracket. No 4101 events "
            "in a 2-hour test.",
            components=["RTX 3070"],
            error_codes=["Display-4101", "0x116"],
            minutes_spent=35,
        ),
    ),
    (
        12,
        dict(
            title="Laptop overheating and shutting down",
            status="fixed",
            category="thermal",
            device_type="laptop",
            device="15-inch gaming laptop, Ryzen 7 5800H / RTX 3060",
            symptoms="Shuts off after 10-15 minutes of gaming. Very loud fans, hot keyboard deck.",
            steps="CPU at 98 C within two minutes of load, clock dropping to 2.9 GHz. Both fans "
            "spinning. Intake and fin stack matted with dust; paste dry and cracked.",
            root_cause="Blocked heatsink fins and dried-out thermal paste.",
            fix="Cleaned fans and fins, repasted CPU and GPU. Peak 84 C under the same load, no "
            "throttling.",
            components=["Ryzen 7 5800H"],
            error_codes=["Kernel-Power-86"],
            minutes_spent=60,
        ),
    ),
    (
        5,
        dict(
            title="Windows freezes for 30 seconds, then carries on",
            status="fixed",
            category="storage",
            device_type="office_pc",
            device="Office desktop, Core i5-8400, 1 TB hard drive",
            symptoms="Whole PC locks up for half a minute several times a day. Disk light solid.",
            steps="Event log: disk 153 (IO retried) and storahci 129 (reset to device), a few disk "
            "7 bad-block events. SMART: reallocated sectors climbing.",
            root_cause="Failing hard drive.",
            fix="Cloned to a 1 TB SATA SSD (clone finished with no read errors) and replaced the "
            "SATA cable.",
            components=["1TB HDD", "SATA SSD"],
            error_codes=["disk-153", "storahci-129", "disk-7"],
            minutes_spent=75,
        ),
    ),
    (
        1,
        dict(
            title="Random blue screens, different code each time",
            status="open",
            category="memory",
            device_type="gaming_pc",
            device="Ryzen 7 7700X / B650 / 2x16 GB DDR5-6000",
            symptoms="MEMORY_MANAGEMENT, PAGE_FAULT_IN_NONPAGED_AREA and SYSTEM_SERVICE_EXCEPTION "
            "over the past two weeks. No pattern to what is running.",
            steps="Windows Memory Diagnostic passed with EXPO off. With EXPO on: MemTest86 errors "
            "in test 6 within 20 minutes. Waiting on a BIOS update to retest before blaming "
            "the kit.",
            components=["Ryzen 7 7700X", "B650", "DDR5"],
            error_codes=["0x1A", "0x50", "0x3B"],
            minutes_spent=50,
        ),
    ),
]


def load_demo(db: Session, settings: Settings) -> tuple[int, int]:
    """Add the demo runs and entries that are not there yet."""
    runs = 0
    for sample in synth.build_all():
        result = ingest(db, settings, sample.zip_bytes(), label=sample.title, is_demo=True)
        runs += int(result.created)

    existing = set(db.scalars(select(WorkLogEntry.title).where(WorkLogEntry.is_demo)))
    today = date.today()
    entries = 0
    for days_ago, fields in DEMO_ENTRIES:
        if fields["title"] in existing:
            continue
        db.add(WorkLogEntry(occurred_on=today - timedelta(days=days_ago), is_demo=True, **fields))
        entries += 1
    db.commit()
    return runs, entries


def clear_demo(db: Session, settings: Settings) -> tuple[int, int]:
    """Remove every demo run and demo work-log entry. Real data is untouched."""
    entries = list(db.scalars(select(WorkLogEntry).where(WorkLogEntry.is_demo)))
    for entry in entries:
        db.delete(entry)
    db.commit()
    runs = list(db.scalars(select(Run).where(Run.is_demo)))
    for run in runs:
        delete_run(db, settings, run)
    return len(runs), len(entries)
