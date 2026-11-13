"""A PC that will not start: what each symptom points at, and what to try.

There is no data to collect from a machine that does not boot, so this is a
guided checklist instead - the order a bench technician works in, cheapest
and most likely first. The entries are technician guidance written for this
project. Motherboard makers differ in the details (LED names, beep patterns),
so the board manual has the last word.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class NoBootSymptom:
    key: str
    title: str  # what the technician sees
    meaning: str
    category: str  # key of model.CATEGORIES
    causes: tuple[str, ...]  # most likely first
    checks: tuple[str, ...]  # in the order to try them

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["causes"] = list(self.causes)
        d["checks"] = list(self.checks)
        return d


_STRIP_DOWN = (
    "Strip it down: CPU, one stick of RAM, no graphics card if the CPU has graphics, "
    "nothing on USB. Add parts back one at a time."
)

SYMPTOMS: tuple[NoBootSymptom, ...] = (
    NoBootSymptom(
        "no_power",
        "Completely dead: no fans, no lights",
        "No power is reaching the board, or the board is not being told to start.",
        "power",
        (
            "Power supply switch off, loose power cable, dead wall socket or power strip",
            "Front-panel power button or its header not connected",
            "Failed power supply",
            "Short circuit (a stray standoff or screw under the board)",
            "Failed motherboard",
        ),
        (
            "Check the switch on the back of the power supply, the cable at both ends, and try "
            "another wall socket.",
            "Reseat the 24-pin and CPU power plugs until they click.",
            "Start it without the case button: briefly touch the two PWR_SW pins with a "
            "screwdriver tip.",
            "Test the power supply with a PSU tester, or swap in a known-good one.",
            "Take the board out of the case and try it on its box (breadboarding) to rule out "
            "a short.",
        ),
    ),
    NoBootSymptom(
        "power_cycles",
        "Starts for a second, then shuts off (maybe repeating)",
        "The board starts, detects something wrong, and cuts power to protect itself.",
        "power",
        (
            "CPU power plug (4/8-pin) not connected",
            "Short circuit or a failing power supply",
            "RAM not seated or not compatible",
            "CPU cooler missing or not detected",
            "Normal memory training on a new build or after clearing CMOS - this can repeat a "
            "few times and take minutes on DDR5",
        ),
        (
            "On a new build or after a BIOS reset, wait a full five minutes first: memory "
            "training looks exactly like this.",
            "Check the CPU power plug at the top of the board.",
            "Reseat the RAM; try one stick in the slot the manual lists first.",
            "Clear CMOS (jumper or battery out for a minute).",
            _STRIP_DOWN,
            "Swap in a known-good power supply.",
        ),
    ),
    NoBootSymptom(
        "fans_no_display",
        "Fans and lights come on, but nothing on screen",
        "The PC has power but does not finish its self-test, or the picture is not reaching "
        "the monitor.",
        "motherboard",
        (
            "Monitor on the wrong input, or cable in the motherboard port instead of the "
            "graphics card",
            "RAM not seated",
            "Graphics card not seated or not powered",
            "BIOS does not support the CPU (needs an update)",
            "Failed RAM, GPU, CPU or board",
        ),
        (
            "Check the monitor's input, and that the cable is in the graphics card, not the "
            "motherboard.",
            "Look for debug LEDs or a code display on the board - they say where it stops.",
            "Reseat the RAM (push until both latches click), then try one stick at a time.",
            "Reseat the graphics card and its power cables; try another cable and port.",
            "Clear CMOS.",
            _STRIP_DOWN,
            "New CPU on an older board: update the BIOS (BIOS Flashback needs no CPU).",
        ),
    ),
    NoBootSymptom(
        "led_cpu",
        "Debug LED stays on: CPU",
        "The board does not detect a working processor.",
        "cpu",
        (
            "CPU power plug (4/8-pin) not connected",
            "BIOS too old for this CPU",
            "Bent socket pins or CPU not seated",
            "Failed CPU or board",
        ),
        (
            "Check the CPU power plug at the top-left of the board.",
            "Check the board's CPU support list: a newer CPU may need a BIOS update first "
            "(BIOS Flashback works without a CPU).",
            "Take the CPU out and inspect the pins (socket pins on Intel and AM5, CPU pins on "
            "AM4) with a light.",
            "Reseat the CPU and cooler - a cooler screwed down unevenly can lift the chip.",
            "Test the CPU in another board, or another CPU in this one.",
        ),
    ),
    NoBootSymptom(
        "led_dram",
        "Debug LED stays on: DRAM (memory)",
        "The board cannot get the memory working.",
        "memory",
        (
            "RAM not fully seated",
            "Memory still training (normal for minutes on DDR5)",
            "XMP/EXPO profile the board cannot run",
            "Wrong slots, or an incompatible kit",
            "A bad stick or slot",
            "Bent CPU socket pins (they carry the memory signals)",
        ),
        (
            "On DDR5 or after clearing CMOS, wait five minutes before touching anything.",
            "Reseat every stick until both ends click.",
            "Try one stick in the slot the manual names first (often A2), then each stick, "
            "then each slot.",
            "Clear CMOS to drop an unstable XMP/EXPO profile.",
            "Update the BIOS (memory support improves a lot between versions).",
            "If no stick works in any slot, inspect the CPU socket pins.",
        ),
    ),
    NoBootSymptom(
        "led_vga",
        "Debug LED stays on: VGA (graphics)",
        "The board does not detect a working graphics output.",
        "gpu",
        (
            "Graphics card not fully seated",
            "Card's power cables missing or loose",
            "CPU has no integrated graphics and the card is not working",
            "Failed graphics card or slot",
        ),
        (
            "Reseat the card until the slot latch clicks; check for sag.",
            "Connect every PCIe power plug the card has, on separate cables.",
            "Try another PCIe slot.",
            "If the CPU has integrated graphics, remove the card and plug the monitor into "
            "the board.",
            "Test the card in another PC.",
        ),
    ),
    NoBootSymptom(
        "led_boot",
        "Debug LED stays on: BOOT",
        "The hardware passed its self-test but no drive to start Windows from was found.",
        "storage",
        (
            "Boot drive not detected (loose M.2 or SATA cable)",
            "Wrong boot order",
            "Windows boot files damaged",
            "Failed drive",
            "Storage mode changed in the BIOS (AHCI / RAID / VMD)",
        ),
        (
            "Enter the BIOS: is the drive listed at all?",
            "Reseat the M.2 drive or replace the SATA cable; try another slot or port.",
            "Set the boot order so Windows Boot Manager is first.",
            "Check the storage mode matches how Windows was installed.",
            "Boot Windows install media and run Startup Repair.",
            "Test the drive in another PC before giving up on its data.",
        ),
    ),
    NoBootSymptom(
        "beeps",
        "Beeps instead of starting",
        "The board is signalling a self-test failure by sound. The pattern is the message.",
        "motherboard",
        ("Memory fault (most common)", "Graphics fault", "CPU or board fault"),
        (
            "Count the pattern (long and short) and look it up in the board manual - patterns "
            "differ between BIOS makers.",
            "As a rule of thumb: repeating or continuous beeps = memory; one long and two or "
            "three short = graphics.",
            "Reseat the RAM, then the graphics card.",
            _STRIP_DOWN,
        ),
    ),
    NoBootSymptom(
        "no_boot_device",
        "Reaches a message like 'No bootable device' or goes straight to the BIOS",
        "The PC works, but it cannot find anything to start Windows from.",
        "storage",
        (
            "Boot order changed, or a USB stick left plugged in",
            "Drive not detected",
            "Windows boot files damaged, often after a failed update or power cut",
            "Failed drive",
        ),
        (
            "Unplug USB sticks and external drives.",
            "In the BIOS, check the drive is listed and Windows Boot Manager is first.",
            "Reseat the drive.",
            "Run Startup Repair from Windows install media; then 'bootrec /rebuildbcd'.",
            "Check the drive's health in another PC and back up before reinstalling.",
        ),
    ),
    NoBootSymptom(
        "repair_loop",
        "Stuck on the logo, spinning dots, or 'Preparing Automatic Repair'",
        "Windows starts loading and fails every time.",
        "os",
        ("A bad update or driver", "Damaged system files", "Failing drive", "Faulty RAM"),
        (
            "Force it off three times in a row to reach the recovery menu.",
            "Try Safe Mode; if it starts, remove the latest driver or update.",
            "Recovery > Uninstall Updates, then System Restore.",
            "From the recovery command prompt: 'chkdsk C: /f', then 'sfc /scannow "
            "/offbootdir=C:\\ /offwindir=C:\\Windows'.",
            "Check the drive's health and test the RAM before reinstalling Windows.",
        ),
    ),
)

BY_KEY = {symptom.key: symptom for symptom in SYMPTOMS}
