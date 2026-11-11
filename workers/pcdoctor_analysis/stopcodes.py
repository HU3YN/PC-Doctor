"""Blue-screen stop codes: what each one means and where a technician looks first.

Every name here was checked against bugcodes.h in the Windows SDK
(10.0.26100) on a real Windows machine - see docs/verified-facts.md. The
meanings, causes and checks are technician guidance, not Microsoft text: a
stop code names what Windows noticed, not the part that failed, so each entry
lists the usual suspects in the order worth checking.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class StopCode:
    code: int
    name: str
    category: str  # key of model.CATEGORIES: where the fault usually is
    meaning: str = ""  # plain English
    causes: tuple[str, ...] = field(default_factory=tuple)  # most likely first
    checks: tuple[str, ...] = field(default_factory=tuple)  # what to do, in order
    hardware_likely: bool = False  # True = usually a part, not software

    @property
    def hex(self) -> str:
        return format_code(self.code)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["hex"] = self.hex
        d["causes"] = list(self.causes)
        d["checks"] = list(self.checks)
        return d


def format_code(code: int) -> str:
    """0x124, 0xC000021A - the short form people type and search for."""
    return f"0x{code:X}"


_RAM_CHECKS = (
    "Run Windows Memory Diagnostic or MemTest86 for at least one full pass.",
    "Turn XMP/EXPO off in the BIOS and retest - unstable memory profiles are common.",
    "Test one stick at a time, in the slot the board manual lists first.",
)
_DRIVER_CHECKS = (
    'Note the driver named on the blue screen or in the event ("Possibly related driver").',
    "Update that driver, or roll it back if the crashes started after an update.",
    "Run 'sfc /scannow' and 'DISM /Online /Cleanup-Image /RestoreHealth'.",
)
_DISK_CHECKS = (
    "Check disk health (SMART / reliability counters) and free space.",
    "Reseat or replace the SATA/NVMe cable or try another M.2 slot.",
    "Run 'chkdsk /scan' and back up the data before anything else.",
)
_GPU_CHECKS = (
    "Clean-install the graphics driver (DDU in Safe Mode, then the current driver).",
    "Check GPU temperature and power: reseat the card and its power cables.",
    "Remove any overclock or undervolt. Test the card in another PC if you can.",
)


_CODES: tuple[StopCode, ...] = (
    StopCode(
        0x124,
        "WHEA_UNCORRECTABLE_ERROR",
        "cpu",
        "The hardware itself reported an error it could not recover from.",
        (
            "CPU overclock, undervolt or unstable voltage",
            "Overheating CPU",
            "Failing CPU, motherboard VRM or power supply",
            "Bad RAM",
        ),
        (
            "Reset the BIOS to defaults: no overclock, no undervolt, no XMP for now.",
            "Check CPU temperature under load and reseat the cooler with fresh paste.",
            "Look at the WHEA-Logger events: they name the component (processor core, "
            "memory, PCI Express).",
            "Update the BIOS. If it still happens at stock settings, suspect CPU, board or PSU.",
        ),
        True,
    ),
    StopCode(
        0x9C,
        "MACHINE_CHECK_EXCEPTION",
        "cpu",
        "The processor detected a fatal hardware error (older form of 0x124).",
        ("Overheating", "Overclock or bad voltage", "Failing CPU, board or PSU"),
        (
            "Reset the BIOS to defaults.",
            "Check cooling and CPU temperature.",
            "Test with a known-good power supply.",
        ),
        True,
    ),
    StopCode(
        0x101,
        "CLOCK_WATCHDOG_TIMEOUT",
        "cpu",
        "A processor core stopped responding to the others.",
        ("CPU overclock or undervolt", "Core voltage too low", "Outdated BIOS", "Failing CPU"),
        (
            "Reset the BIOS to defaults and remove any overclock or undervolt.",
            "Update the BIOS (it carries CPU microcode).",
            "Stress-test the CPU; if one core keeps failing, the CPU is the suspect.",
        ),
        True,
    ),
    StopCode(
        0x1A,
        "MEMORY_MANAGEMENT",
        "memory",
        "Windows found its memory bookkeeping damaged.",
        (
            "Faulty or unstable RAM",
            "XMP/EXPO profile the board cannot hold",
            "A driver corrupting memory",
            "Failing drive holding the page file",
        ),
        _RAM_CHECKS + ("If memory tests pass, look for a driver update or a failing drive.",),
        True,
    ),
    StopCode(
        0x50,
        "PAGE_FAULT_IN_NONPAGED_AREA",
        "memory",
        "Something asked for memory that was not there.",
        ("Faulty RAM", "A buggy driver or antivirus", "Corrupt system files", "Failing drive"),
        _RAM_CHECKS + _DRIVER_CHECKS[:2],
    ),
    StopCode(
        0x4E,
        "PFN_LIST_CORRUPT",
        "memory",
        "The list Windows uses to track physical memory pages is corrupt.",
        ("Faulty RAM", "A driver writing where it should not"),
        _RAM_CHECKS,
        True,
    ),
    StopCode(
        0x12B,
        "FAULTY_HARDWARE_CORRUPTED_PAGE",
        "memory",
        "A memory page changed by itself - a single bit flipped.",
        ("Faulty RAM", "Unstable memory overclock", "Failing drive or controller"),
        _RAM_CHECKS,
        True,
    ),
    StopCode(
        0x19,
        "BAD_POOL_HEADER",
        "driver",
        "A block of kernel memory was damaged.",
        ("A buggy driver", "Faulty RAM", "Antivirus or disk-filter software"),
        _DRIVER_CHECKS + _RAM_CHECKS[:1],
    ),
    StopCode(
        0xC2,
        "BAD_POOL_CALLER",
        "driver",
        "A driver made an invalid memory request.",
        ("A buggy or outdated driver", "Recently installed software"),
        _DRIVER_CHECKS,
    ),
    StopCode(
        0xC5,
        "DRIVER_CORRUPTED_EXPOOL",
        "driver",
        "A driver damaged kernel memory.",
        ("A buggy driver", "Faulty RAM"),
        _DRIVER_CHECKS + _RAM_CHECKS[:1],
    ),
    StopCode(
        0xA,
        "IRQL_NOT_LESS_OR_EQUAL",
        "driver",
        "Something in the kernel touched memory it was not allowed to at that moment.",
        ("A buggy driver", "Faulty or unstable RAM", "Overclock"),
        _DRIVER_CHECKS + _RAM_CHECKS[:2],
    ),
    StopCode(
        0xD1,
        "DRIVER_IRQL_NOT_LESS_OR_EQUAL",
        "driver",
        "A driver touched memory it was not allowed to at that moment.",
        ("A buggy driver - network, audio and storage drivers are the usual ones", "Faulty RAM"),
        _DRIVER_CHECKS,
    ),
    StopCode(
        0x1E,
        "KMODE_EXCEPTION_NOT_HANDLED",
        "driver",
        "A kernel program hit an error nothing caught.",
        ("A buggy driver", "Faulty RAM", "Outdated BIOS"),
        _DRIVER_CHECKS + _RAM_CHECKS[:1],
    ),
    StopCode(
        0x8E,
        "KERNEL_MODE_EXCEPTION_NOT_HANDLED",
        "driver",
        "A kernel program hit an error nothing caught.",
        ("A buggy driver", "Faulty RAM"),
        _DRIVER_CHECKS + _RAM_CHECKS[:1],
    ),
    StopCode(
        0x1000008E,
        "KERNEL_MODE_EXCEPTION_NOT_HANDLED_M",
        "driver",
        "A kernel program hit an error nothing caught.",
        ("A buggy driver", "Faulty RAM"),
        _DRIVER_CHECKS + _RAM_CHECKS[:1],
    ),
    StopCode(
        0x7E,
        "SYSTEM_THREAD_EXCEPTION_NOT_HANDLED",
        "driver",
        "A system thread crashed, almost always inside a driver.",
        ("A buggy or incompatible driver - often graphics", "Corrupt system files"),
        _DRIVER_CHECKS,
    ),
    StopCode(
        0x1000007E,
        "SYSTEM_THREAD_EXCEPTION_NOT_HANDLED_M",
        "driver",
        "A system thread crashed, almost always inside a driver.",
        ("A buggy or incompatible driver - often graphics", "Corrupt system files"),
        _DRIVER_CHECKS,
    ),
    StopCode(
        0x3B,
        "SYSTEM_SERVICE_EXCEPTION",
        "driver",
        "A system call crashed while running kernel code.",
        ("A buggy driver - often graphics or antivirus", "Corrupt system files", "Faulty RAM"),
        _DRIVER_CHECKS + _RAM_CHECKS[:1],
    ),
    StopCode(
        0x7F,
        "UNEXPECTED_KERNEL_MODE_TRAP",
        "cpu",
        "The processor raised an error the kernel could not handle.",
        ("Faulty or unstable RAM", "Overclock or overheating", "A buggy driver"),
        ("Reset the BIOS to defaults.",) + _RAM_CHECKS[:1] + _DRIVER_CHECKS[:2],
        True,
    ),
    StopCode(
        0x133,
        "DPC_WATCHDOG_VIOLATION",
        "driver",
        "A driver kept the processor busy for far too long.",
        ("Storage driver or SSD firmware", "A buggy driver", "Failing drive"),
        ("Update the SSD firmware and the storage controller driver.",)
        + _DRIVER_CHECKS[:2]
        + _DISK_CHECKS[:1],
    ),
    StopCode(
        0x9F,
        "DRIVER_POWER_STATE_FAILURE",
        "driver",
        "A driver got stuck while the PC was sleeping, waking or shutting down.",
        ("A driver that mishandles sleep - network, USB, graphics", "Outdated BIOS"),
        (
            "Update chipset, network, USB and graphics drivers.",
            "Update the BIOS.",
            "Turn off Fast Startup and retest.",
        ),
    ),
    StopCode(
        0xA0,
        "INTERNAL_POWER_ERROR",
        "power",
        "Windows' power manager hit a fatal error, often around sleep or hibernate.",
        ("A driver that mishandles sleep", "Hibernate file problems", "Outdated BIOS"),
        (
            "Update chipset and graphics drivers and the BIOS.",
            "Turn hibernate off and on again: 'powercfg /h off' then 'powercfg /h on'.",
        ),
    ),
    StopCode(
        0x116,
        "VIDEO_TDR_FAILURE",
        "gpu",
        "The graphics driver stopped responding and could not be restarted.",
        (
            "Graphics driver problem",
            "Overheating or failing GPU",
            "Not enough power to the card",
            "GPU overclock or undervolt",
        ),
        _GPU_CHECKS,
        True,
    ),
    StopCode(
        0x117,
        "VIDEO_TDR_TIMEOUT_DETECTED",
        "gpu",
        "The graphics driver stopped responding (it was restarted).",
        ("Graphics driver problem", "Overheating or failing GPU", "GPU overclock"),
        _GPU_CHECKS,
    ),
    StopCode(
        0x141,
        "VIDEO_ENGINE_TIMEOUT_DETECTED",
        "gpu",
        "Part of the graphics card stopped responding.",
        ("Graphics driver problem", "Overheating or failing GPU"),
        _GPU_CHECKS,
    ),
    StopCode(
        0x119,
        "VIDEO_SCHEDULER_INTERNAL_ERROR",
        "gpu",
        "Windows' graphics scheduler hit a fatal error.",
        ("Graphics driver problem", "Failing GPU or its memory", "GPU overclock"),
        _GPU_CHECKS,
        True,
    ),
    StopCode(
        0x113,
        "VIDEO_DXGKRNL_FATAL_ERROR",
        "gpu",
        "The DirectX graphics kernel hit a fatal error.",
        ("Graphics driver problem", "Failing GPU"),
        _GPU_CHECKS,
    ),
    StopCode(
        0x10E,
        "VIDEO_MEMORY_MANAGEMENT_INTERNAL",
        "gpu",
        "Windows' video memory manager hit a fatal error.",
        ("Graphics driver problem", "Failing video memory"),
        _GPU_CHECKS,
    ),
    StopCode(
        0x7A,
        "KERNEL_DATA_INPAGE_ERROR",
        "storage",
        "Windows could not read its own data back from the drive.",
        ("Failing drive", "Bad cable or M.2 contact", "Faulty RAM", "File system damage"),
        _DISK_CHECKS + _RAM_CHECKS[:1],
        True,
    ),
    StopCode(
        0x77,
        "KERNEL_STACK_INPAGE_ERROR",
        "storage",
        "Windows could not read kernel data back from the page file.",
        ("Failing drive", "Bad cable", "Faulty RAM"),
        _DISK_CHECKS + _RAM_CHECKS[:1],
        True,
    ),
    StopCode(
        0x7B,
        "INACCESSIBLE_BOOT_DEVICE",
        "storage",
        "Windows lost access to the drive it boots from.",
        (
            "Storage mode changed in BIOS (AHCI/RAID/VMD)",
            "Missing storage driver",
            "Failing boot drive",
            "Corrupt boot files after an update",
        ),
        (
            "Check the BIOS storage mode matches how Windows was installed.",
            "Confirm the BIOS still sees the drive.",
            "Use Startup Repair from recovery media; check the drive's health.",
        ),
    ),
    StopCode(
        0xED,
        "UNMOUNTABLE_BOOT_VOLUME",
        "storage",
        "Windows could not mount the boot volume.",
        ("File system damage, often after power loss", "Failing drive", "Bad cable"),
        ("Run 'chkdsk C: /r' from recovery media.",) + _DISK_CHECKS[:2],
    ),
    StopCode(
        0x24,
        "NTFS_FILE_SYSTEM",
        "storage",
        "The NTFS file system driver hit a fatal error.",
        ("File system corruption", "Failing drive", "Faulty RAM"),
        _DISK_CHECKS + _RAM_CHECKS[:1],
    ),
    StopCode(
        0x154,
        "UNEXPECTED_STORE_EXCEPTION",
        "storage",
        "Windows' memory store hit an unexpected error - usually the drive under it.",
        ("Failing SSD or HDD", "Storage driver", "Faulty RAM"),
        _DISK_CHECKS + _RAM_CHECKS[:1],
        True,
    ),
    StopCode(
        0xEF,
        "CRITICAL_PROCESS_DIED",
        "os",
        "A process Windows cannot run without stopped.",
        ("Corrupt system files", "Failing drive", "A bad update or driver", "Faulty RAM"),
        ("Run 'sfc /scannow' and 'DISM /Online /Cleanup-Image /RestoreHealth'.",)
        + _DISK_CHECKS[:1]
        + ("Uninstall the most recent update or driver.",),
    ),
    StopCode(
        0xF4,
        "CRITICAL_OBJECT_TERMINATION",
        "os",
        "A process or thread Windows cannot run without ended.",
        ("Failing drive or cable", "Corrupt system files", "Faulty RAM"),
        _DISK_CHECKS[:2] + ("Run 'sfc /scannow'.",),
    ),
    StopCode(
        0xC000021A,
        "WINLOGON_FATAL_ERROR",
        "os",
        "A core user-mode part of Windows (Winlogon or CSRSS) failed.",
        ("Corrupt system files", "A bad update", "Third-party software replacing system files"),
        (
            "Boot to recovery and uninstall the latest update.",
            "Run 'sfc /scannow' offline from recovery media.",
            "Use System Restore.",
        ),
    ),
    StopCode(
        0x74,
        "BAD_SYSTEM_CONFIG_INFO",
        "os",
        "The registry's system hive is damaged or misconfigured.",
        ("Registry corruption, often after power loss", "Wrong boot configuration", "Faulty RAM"),
        (
            "Use Startup Repair or System Restore from recovery media.",
            "Check boot configuration with 'bcdedit'.",
        )
        + _RAM_CHECKS[:1],
    ),
    StopCode(
        0x51,
        "REGISTRY_ERROR",
        "os",
        "Windows hit a fatal error reading the registry.",
        ("Failing drive", "Registry corruption"),
        _DISK_CHECKS[:1] + ("Use System Restore from recovery media.",),
    ),
    StopCode(
        0x139,
        "KERNEL_SECURITY_CHECK_FAILURE",
        "driver",
        "The kernel found a critical data structure had been corrupted.",
        ("A buggy driver", "Faulty RAM", "Corrupt system files"),
        _DRIVER_CHECKS + _RAM_CHECKS[:1],
    ),
    StopCode(
        0x13A,
        "KERNEL_MODE_HEAP_CORRUPTION",
        "driver",
        "The kernel's memory heap was corrupted.",
        ("A buggy driver", "Faulty RAM"),
        _DRIVER_CHECKS + _RAM_CHECKS[:1],
    ),
    StopCode(
        0x109,
        "CRITICAL_STRUCTURE_CORRUPTION",
        "driver",
        "Kernel code or data was changed when it must never be.",
        ("A driver modifying the kernel", "Faulty RAM", "Malware"),
        _RAM_CHECKS[:1] + _DRIVER_CHECKS[:2] + ("Run a full malware scan.",),
    ),
    StopCode(
        0xBE,
        "ATTEMPTED_WRITE_TO_READONLY_MEMORY",
        "driver",
        "A driver tried to write to read-only memory.",
        ("A buggy driver", "Faulty RAM"),
        _DRIVER_CHECKS + _RAM_CHECKS[:1],
    ),
    StopCode(
        0xFC,
        "ATTEMPTED_EXECUTE_OF_NOEXECUTE_MEMORY",
        "driver",
        "A driver tried to run code from memory marked as data.",
        ("A buggy driver", "Faulty RAM", "Malware"),
        _DRIVER_CHECKS + _RAM_CHECKS[:1],
    ),
    StopCode(
        0xC4,
        "DRIVER_VERIFIER_DETECTED_VIOLATION",
        "driver",
        "Driver Verifier caught a driver breaking the rules.",
        ("The driver named on the blue screen", "Driver Verifier left switched on"),
        (
            "Update or remove the named driver.",
            "Turn Driver Verifier off with 'verifier /reset' once you are done testing.",
        ),
    ),
    StopCode(
        0x10D,
        "WDF_VIOLATION",
        "driver",
        "A driver broke the Windows Driver Framework rules.",
        ("A buggy driver - USB and peripheral drivers are common",),
        _DRIVER_CHECKS,
    ),
    StopCode(
        0x144,
        "BUGCODE_USB3_DRIVER",
        "peripheral",
        "The USB 3 driver hit a fatal error.",
        ("A faulty USB device or hub", "USB controller driver", "Outdated BIOS"),
        (
            "Unplug USB devices and add them back one at a time.",
            "Update chipset and USB controller drivers.",
            "Update the BIOS.",
        ),
    ),
    StopCode(
        0xFE,
        "BUGCODE_USB_DRIVER",
        "peripheral",
        "A USB driver hit a fatal error.",
        ("A faulty USB device or hub", "USB controller driver"),
        (
            "Unplug USB devices and add them back one at a time.",
            "Update chipset and USB controller drivers.",
        ),
    ),
    StopCode(
        0x7C,
        "BUGCODE_NDIS_DRIVER",
        "network",
        "A network driver hit a fatal error.",
        ("Network adapter driver", "VPN or firewall software"),
        ("Update or reinstall the network adapter driver.", "Remove VPN/firewall add-ons."),
    ),
    StopCode(
        0xA5,
        "ACPI_BIOS_ERROR",
        "motherboard",
        "The BIOS's ACPI tables do not meet what Windows needs.",
        ("Outdated or misconfigured BIOS", "Incompatible hardware change"),
        ("Update the BIOS and load its defaults.",),
    ),
    StopCode(
        0x18B,
        "SECURE_KERNEL_ERROR",
        "os",
        "The secure kernel (virtualization-based security) hit a fatal error.",
        ("A driver incompatible with memory integrity", "Outdated BIOS or firmware"),
        (
            "Update the BIOS and chipset drivers.",
            "Check Windows Security > Device security > Core isolation for blocked drivers.",
        ),
    ),
    StopCode(
        0x1CA,
        "SYNTHETIC_WATCHDOG_TIMEOUT",
        "cpu",
        "The whole system stopped responding and a watchdog reset it.",
        ("CPU overclock or undervolt", "Unstable power", "Firmware problem"),
        ("Reset the BIOS to defaults.", "Update the BIOS.", "Test with a known-good PSU."),
        True,
    ),
    StopCode(
        0x3D,
        "INTERRUPT_EXCEPTION_NOT_HANDLED",
        "driver",
        "An error happened while handling a hardware interrupt.",
        ("A buggy driver", "Failing device"),
        _DRIVER_CHECKS,
    ),
    StopCode(
        0x4A,
        "IRQL_GT_ZERO_AT_SYSTEM_SERVICE",
        "driver",
        "A driver returned to user mode in the wrong state.",
        ("A buggy driver",),
        _DRIVER_CHECKS,
    ),
    StopCode(
        0x162,
        "KERNEL_AUTO_BOOST_INVALID_LOCK_RELEASE",
        "driver",
        "A driver released a lock it did not hold.",
        ("A buggy driver - often Bluetooth or network",),
        _DRIVER_CHECKS,
    ),
    StopCode(
        0x135,
        "REGISTRY_FILTER_DRIVER_EXCEPTION",
        "driver",
        "A registry filter driver crashed - usually security software.",
        ("Antivirus or anti-cheat software",),
        ("Update or remove the security or anti-cheat software involved.",),
    ),
    StopCode(
        0xE2,
        "MANUALLY_INITIATED_CRASH",
        "other",
        "Someone triggered this crash on purpose (keyboard shortcut or debugger).",
        ("Crash-on-Ctrl+Scroll setting", "A debugging tool"),
        ("Nothing is wrong with the hardware. Check who or what triggered it.",),
    ),
    StopCode(
        0x1C8,
        "MANUALLY_INITIATED_POWER_BUTTON_HOLD",
        "other",
        "The power button was held down to force the PC off while it was hung.",
        ("The system had frozen and the user forced it off",),
        ("Treat it as a hard freeze: check temperatures, RAM and drivers for the hang.",),
    ),
)

# Names only, for codes without written guidance yet (all from bugcodes.h).
_NAMES_ONLY: dict[int, str] = {
    0x1: "APC_INDEX_MISMATCH",
    0x12: "TRAP_CAUSE_UNKNOWN",
    0x18: "REFERENCE_BY_POINTER",
    0x23: "FAT_FILE_SYSTEM",
    0x2E: "DATA_BUS_ERROR",
    0x34: "CACHE_MANAGER",
    0x44: "MULTIPLE_IRP_COMPLETE_REQUESTS",
    0x4C: "FATAL_UNHANDLED_HARD_ERROR",
    0x5C: "HAL_INITIALIZATION_FAILED",
    0x5D: "UNSUPPORTED_PROCESSOR",
    0x76: "PROCESS_HAS_LOCKED_PAGES",
    0x79: "MISMATCHED_HAL",
    0x80: "NMI_HARDWARE_FAILURE",
    0xA2: "MEMORY_IMAGE_CORRUPT",
    0xB8: "ATTEMPTED_SWITCH_FROM_DPC",
    0xC1: "SPECIAL_POOL_DETECTED_MEMORY_CORRUPTION",
    0xC6: "DRIVER_CAUGHT_MODIFYING_FREED_POOL",
    0xC7: "TIMER_OR_DPC_INVALID",
    0xC9: "DRIVER_VERIFIER_IOMANAGER_VIOLATION",
    0xCA: "PNP_DETECTED_FATAL_ERROR",
    0xCE: "DRIVER_UNLOADED_WITHOUT_CANCELLING_PENDING_OPERATIONS",
    0xD5: "DRIVER_PAGE_FAULT_IN_FREED_SPECIAL_POOL",
    0xDA: "SYSTEM_PTE_MISUSE",
    0xE6: "DRIVER_VERIFIER_DMA_VIOLATION",
    0xEA: "THREAD_STUCK_IN_DEVICE_DRIVER",
    0xF7: "DRIVER_OVERRAN_STACK_BUFFER",
    0x102: "DPC_WATCHDOG_TIMEOUT",
    0x108: "THIRD_PARTY_FILE_SYSTEM_FAILURE",
    0x111: "RECURSIVE_NMI",
    0x11D: "EVENT_TRACING_FATAL_ERROR",
    0x122: "WHEA_INTERNAL_ERROR",
    0x12C: "EXFAT_FILE_SYSTEM",
    0x13C: "INVALID_IO_BOOST_STATE",
    0x140: "STORAGE_DEVICE_ABNORMALITY_DETECTED",
    0x145: "SECURE_BOOT_VIOLATION",
    0x149: "REFS_FILE_SYSTEM",
    0x14F: "PDC_WATCHDOG_TIMEOUT",
    0x15F: "CONNECTED_STANDBY_WATCHDOG_TIMEOUT_LIVEDUMP",
    0x164: "WIN32K_CRITICAL_FAILURE",
    0x17E: "MICROCODE_REVISION_MISMATCH",
    0x18C: "HYPERGUARD_VIOLATION",
    0x19C: "WIN32K_POWER_WATCHDOG_TIMEOUT",
    0x1A0: "TTM_WATCHDOG_TIMEOUT",
    0x1C7: "STORE_DATA_STRUCTURE_CORRUPTION",
    0x1CF: "HARDWARE_WATCHDOG_TIMEOUT",
    0x1D0: "ACPI_FIRMWARE_WATCHDOG_TIMEOUT",
    0x1D5: "DRIVER_PNP_WATCHDOG",
    0x1DB: "IPI_WATCHDOG_TIMEOUT",
    0x1DF: "PROCESSOR_START_TIMEOUT",
    0x20001: "HYPERVISOR_ERROR",
    0x10000050: "PAGE_FAULT_IN_NONPAGED_AREA_M",
    0x1000007F: "UNEXPECTED_KERNEL_MODE_TRAP_M",
    0x100000EA: "THREAD_STUCK_IN_DEVICE_DRIVER_M",
}

STOP_CODES: dict[int, StopCode] = {entry.code: entry for entry in _CODES}
for _code, _name in _NAMES_ONLY.items():
    STOP_CODES.setdefault(_code, StopCode(_code, _name, "other"))

_HEX = re.compile(r"(?<![0-9A-Za-z])0[xX]([0-9A-Fa-f]{1,8})(?![0-9A-Za-z])")


def parse_code(text: str | int | None) -> int | None:
    """Turn '0x00000124', '0x124', '124' or 292 into the number 0x124.

    A bare string of digits is read as hex, because that is how stop codes are
    written everywhere ("stop code 124"). Integers are taken as they are.
    """
    if text is None:
        return None
    if isinstance(text, int):
        return text if 0 <= text <= 0xFFFFFFFF else None
    cleaned = text.strip()
    if not cleaned:
        return None
    match = _HEX.search(cleaned)
    if match:
        return int(match.group(1), 16)
    bare = cleaned.lstrip("0") or "0"
    if re.fullmatch(r"[0-9A-Fa-f]{1,8}", bare):
        return int(bare, 16)
    return None


def lookup(text: str | int | None) -> StopCode | None:
    """Find a stop code by number ('0x124') or by name ('WHEA_UNCORRECTABLE_ERROR')."""
    if isinstance(text, str):
        wanted = text.strip().upper().replace(" ", "_")
        for entry in STOP_CODES.values():
            if entry.name == wanted:
                return entry
    code = parse_code(text)
    return STOP_CODES.get(code) if code is not None else None


def search(query: str, limit: int = 20) -> list[StopCode]:
    """Stop codes whose number or name matches the query, best first."""
    query = query.strip()
    if not query:
        return sorted(_CODES, key=lambda e: e.code)[:limit]
    exact = lookup(query)
    words = [w for w in re.split(r"[\s_]+", query.upper()) if w]
    scored: list[tuple[int, StopCode]] = []
    for entry in STOP_CODES.values():
        if exact and entry.code == exact.code:
            continue
        haystack = f"{entry.name} {entry.hex.upper()} {entry.meaning.upper()}"
        hits = sum(1 for w in words if w in haystack)
        if hits == len(words):
            # Entries with written guidance first, then by code.
            scored.append((0 if entry.meaning else 1, entry))
    scored.sort(key=lambda pair: (pair[0], pair[1].code))
    results = [entry for _, entry in scored]
    if exact:
        results.insert(0, exact)
    return results[:limit]


def extract_codes(text: str) -> list[str]:
    """Every 0x... code in a piece of text, as short hex strings, in order."""
    seen: list[str] = []
    for match in _HEX.finditer(text or ""):
        code = format_code(int(match.group(1), 16))
        if code not in seen:
            seen.append(code)
    return seen
