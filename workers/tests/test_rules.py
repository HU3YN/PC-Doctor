"""Each rule: fires on its fault, stays quiet just under the line, and says
"no data" (None) instead of guessing when its input is missing."""

from __future__ import annotations

import pytest

from pcdoctor_analysis.model import Severity, Thresholds
from pcdoctor_analysis.rules import (
    all_rules,
    events,
    performance,
    run_rules,
    storage,
    system,
    thermal,
)

from .conftest import event, make_frames, make_run, make_sensors

T = Thresholds()
GB = 1024**3
WHEA = "Microsoft-Windows-WHEA-Logger"
KP = "Microsoft-Windows-Kernel-Power"
WER = "Microsoft-Windows-WER-SystemErrorReporting"


def one(findings):
    assert findings is not None and len(findings) == 1, findings
    return findings[0]


# ------------------------------------------------------------ the registry


def test_rule_codes_are_unique_and_namespaced():
    rules = all_rules()
    codes = [r.code for r in rules]
    assert len(codes) == len(set(codes)) >= 29
    assert all("." in code for code in codes)
    from pcdoctor_analysis.model import CATEGORIES

    assert all(r.category in CATEGORIES for r in rules)


def test_counts_read_naturally():
    from pcdoctor_analysis.rules import tidy_plurals

    assert tidy_plurals("3 blue screen(s): 0x124") == "3 blue screens: 0x124"
    assert tidy_plurals("1 blue screen(s) and 2 other code(s)") == "1 blue screen and 2 other codes"
    assert (
        tidy_plurals("stopped responding 1 time(s) (3 event(s))")
        == "stopped responding 1 time (3 events)"
    )
    assert tidy_plurals("2 crash(es) where Windows") == "2 crashes where Windows"
    assert tidy_plurals("nothing to change (s)") == "nothing to change (s)"
    findings, _, _ = run_rules(make_run(events=[event(KP, 86), event(KP, 41, BugcheckCode=0)]))
    assert [f.title for f in findings] == [
        "Windows shut down for overheating 1 time",  # critical, so first
        "1 unexpected shutdown with no stop code",
    ]


def test_an_empty_run_checks_nothing_and_finds_nothing():
    findings, checks, errors = run_rules(make_run())
    assert findings == [] and errors == []
    assert {c.status for c in checks} == {"no_data"}


def test_a_broken_rule_does_not_stop_the_others(monkeypatch):
    from pcdoctor_analysis import rules as registry

    registry.all_rules()
    broken = registry._REGISTRY["thermal.cpu_hot"]

    def explode(run, t):
        raise RuntimeError("boom")

    monkeypatch.setitem(
        registry._REGISTRY,
        "thermal.cpu_hot",
        registry.Rule(**{**broken.__dict__, "function": explode}),
    )
    run = make_run(events=[event(KP, 86)])
    findings, checks, errors = run_rules(run)
    assert [f.code for f in findings] == ["thermal.shutdown"]
    assert any("boom" in e for e in errors)
    assert next(c for c in checks if c.code == "thermal.cpu_hot").status == "error"


def test_findings_are_sorted_worst_first_and_causes_before_symptoms():
    run = make_run(
        events=[event(KP, 86)],
        frames=make_frames(([10.0] * 100 + [200.0]) * 20),
        sensors=make_sensors(cpu_temp_c=[92.0] * 30, gpu_load_pct=[99.0] * 30),
    )
    codes = [f.code for f in run_rules(run)[0]]
    assert codes == [
        "thermal.shutdown",
        "thermal.cpu_hot",
        "performance.stutter",
        "performance.gpu_limited",
    ]


# ------------------------------------------------------------- performance


def test_stutter_needs_a_capture_long_enough_to_judge():
    assert performance.stutter(make_run(), T) is None
    assert performance.stutter(make_run(frames=make_frames([10.0] * 50)), T) is None


def test_stutter_quiet_on_smooth_frames_and_fires_on_spikes():
    assert performance.stutter(make_run(frames=make_frames([10.0] * 3000)), T) == []
    finding = one(
        performance.stutter(make_run(frames=make_frames(([10.0] * 150 + [120.0]) * 20)), T)
    )
    assert finding.severity is Severity.WARNING
    assert finding.evidence["spike_count"] == 20
    assert finding.evidence["hitch_count"] == 20


def test_stutter_fires_on_poor_lows_even_without_isolated_spikes():
    # A second of 100 FPS then a slow patch at 25 FPS, repeated: no single-frame spikes.
    frames = ([10.0] * 100 + [40.0] * 12) * 30
    finding = one(performance.stutter(make_run(frames=make_frames(frames)), T))
    assert finding.evidence["fps_1pct_low"] < 0.45 * finding.evidence["avg_fps"]


def test_gpu_limited_from_sensors_and_from_presentmon():
    assert performance.gpu_limited(make_run(), T) is None
    assert (
        performance.gpu_limited(make_run(sensors=make_sensors(gpu_load_pct=[80.0] * 20)), T) == []
    )
    by_sensor = one(
        performance.gpu_limited(make_run(sensors=make_sensors(gpu_load_pct=[98.0] * 20)), T)
    )
    assert by_sensor.severity is Severity.INFO
    frames = make_frames([10.0] * 400, gpu_busy_ms=[9.8] * 400)
    assert (
        one(performance.gpu_limited(make_run(frames=frames), T)).code == "performance.gpu_limited"
    )


def test_cpu_limited_needs_a_waiting_gpu_and_a_busy_core():
    quiet = make_sensors(gpu_load_pct=[60.0] * 20, cpu_core_max_load_pct=[50.0] * 20)
    assert performance.cpu_limited(make_run(sensors=quiet), T) == []
    busy = make_sensors(gpu_load_pct=[60.0] * 20, cpu_core_max_load_pct=[97.0] * 20)
    assert one(performance.cpu_limited(make_run(sensors=busy), T)).severity is Severity.INFO
    gpu_bound = make_sensors(gpu_load_pct=[98.0] * 20, cpu_core_max_load_pct=[97.0] * 20)
    assert performance.cpu_limited(make_run(sensors=gpu_bound), T) == []
    assert (
        performance.cpu_limited(make_run(sensors=make_sensors(gpu_load_pct=[60.0] * 20)), T) is None
    )


# ----------------------------------------------------------------- thermal


@pytest.mark.parametrize(
    "temps, expected",
    [
        ([70.0] * 60, None),
        ([70.0] * 59 + [89.9], None),
        ([70.0] * 59 + [91.0], Severity.WARNING),  # a peak over the warning line
        ([86.0] * 20 + [70.0] * 40, Severity.WARNING),  # sustained: a third of the run hot
        ([86.0] * 10 + [70.0] * 50, None),  # hot for only a sixth of the run
        ([70.0] * 59 + [100.0], Severity.CRITICAL),
    ],
)
def test_cpu_hot_thresholds(temps, expected):
    findings = thermal.cpu_hot(make_run(sensors=make_sensors(cpu_temp_c=temps)), T)
    if expected is None:
        assert findings == []
    else:
        assert one(findings).severity is expected


def test_cpu_hot_without_a_temperature_sensor_is_no_data():
    assert thermal.cpu_hot(make_run(sensors=make_sensors(gpu_temp_c=[60.0] * 5)), T) is None


def test_cpu_throttling_compares_clock_when_hot_and_cool_under_load():
    sensors = make_sensors(
        cpu_temp_c=[70.0] * 20 + [95.0] * 20,
        cpu_clock_mhz=[4800.0] * 20 + [3400.0] * 20,
        cpu_load_pct=[90.0] * 40,
    )
    finding = one(thermal.cpu_throttling(make_run(sensors=sensors), T))
    assert finding.evidence["drop"] == pytest.approx(1 - 3400 / 4800, abs=1e-3)


def test_cpu_clock_dropping_at_idle_is_not_throttling():
    sensors = make_sensors(
        cpu_temp_c=[70.0] * 20 + [95.0] * 20,
        cpu_clock_mhz=[4800.0] * 20 + [3400.0] * 20,
        cpu_load_pct=[90.0] * 20 + [5.0] * 20,  # the "hot" half is idle
    )
    assert thermal.cpu_throttling(make_run(sensors=sensors), T) == []


def test_cpu_throttling_quiet_when_clock_holds_or_never_hot():
    steady = make_sensors(cpu_temp_c=[70.0] * 20 + [95.0] * 20, cpu_clock_mhz=[4800.0] * 40)
    assert thermal.cpu_throttling(make_run(sensors=steady), T) == []
    cool = make_sensors(cpu_temp_c=[60.0] * 40, cpu_clock_mhz=[4800.0] * 20 + [3000.0] * 20)
    assert thermal.cpu_throttling(make_run(sensors=cool), T) == []
    assert thermal.cpu_throttling(make_run(sensors=make_sensors(cpu_temp_c=[95.0] * 40)), T) is None


def test_cpu_throttling_works_from_windows_counters_alone():
    sensors = make_sensors(
        cpu_temp_c=[70.0] * 20 + [95.0] * 20, cpu_perf_pct=[120.0] * 20 + [80.0] * 20
    )
    assert one(thermal.cpu_throttling(make_run(sensors=sensors), T)).evidence["clock_unit"] != "MHz"


def test_gpu_hot_core_and_hot_spot():
    assert thermal.gpu_hot(make_run(sensors=make_sensors(gpu_temp_c=[80.0] * 10)), T) == []
    assert (
        one(thermal.gpu_hot(make_run(sensors=make_sensors(gpu_temp_c=[88.0] * 10)), T)).severity
        is Severity.WARNING
    )
    assert (
        one(thermal.gpu_hot(make_run(sensors=make_sensors(gpu_temp_c=[96.0] * 10)), T)).severity
        is Severity.CRITICAL
    )
    spot = make_sensors(gpu_temp_c=[75.0] * 10, gpu_hotspot_c=[104.0] * 10)
    assert one(thermal.gpu_hot(make_run(sensors=spot), T)).evidence["gpu_hotspot_max_c"] == 104.0


def test_gpu_throttling():
    sensors = make_sensors(
        gpu_temp_c=[70.0] * 20 + [86.0] * 20,
        gpu_clock_mhz=[1900.0] * 20 + [1500.0] * 20,
        gpu_load_pct=[99.0] * 40,
    )
    assert one(thermal.gpu_throttling(make_run(sensors=sensors), T)).severity is Severity.WARNING


def test_thermal_shutdown_event():
    assert thermal.thermal_shutdown(make_run(), T) is None
    assert thermal.thermal_shutdown(make_run(events=[]), T) == []
    finding = one(thermal.thermal_shutdown(make_run(events=[event(KP, 86)]), T))
    assert finding.severity is Severity.CRITICAL and finding.error_codes == ["Kernel-Power-86"]


# ------------------------------------------------------------------ events

FATAL_CPU = "A fatal hardware error has occurred.\n\nReported by component: Processor Core\nError Source: Machine Check Exception\nError Type: Cache Hierarchy Error\nProcessor APIC ID: 4"
CORRECTED_PCI = "A corrected hardware error has occurred.\n\nComponent: PCI Express Root Port\nError Source: Advanced Error Reporting (PCI Express)\n\nBus:Device:Function: 0x0:0x1:0x1"
CORRECTED_MEM = "A corrected hardware error has occurred.\n\nComponent: Memory\nError Source: Corrected Machine Check"


def test_whea_fatal_names_the_component_and_points_at_the_cpu():
    run = make_run(events=[event(WHEA, 18, FATAL_CPU), event(WHEA, 18, FATAL_CPU)])
    finding = one(events.whea_fatal(run, T))
    assert finding.severity is Severity.CRITICAL
    assert finding.category == "cpu"
    assert finding.evidence["components"] == {"Processor Core": 2}
    assert finding.evidence["error_types"] == {"Cache Hierarchy Error": 2}
    assert finding.error_codes == ["WHEA-18"]
    assert events.whea_corrected(run, T) == []


def test_whea_corrected_is_a_warning_and_follows_the_component():
    pci = one(
        events.whea_corrected(make_run(events=[event(WHEA, 17, CORRECTED_PCI, "Warning")] * 3), T)
    )
    assert pci.severity is Severity.WARNING and pci.category == "motherboard"
    mem = one(
        events.whea_corrected(make_run(events=[event(WHEA, 47, CORRECTED_MEM, "Warning")]), T)
    )
    assert mem.category == "memory"
    assert events.whea_fatal(make_run(events=[event(WHEA, 47, CORRECTED_MEM, "Warning")]), T) == []


def test_whea_event_29_is_fatal_despite_its_warning_level():
    # Windows defines id 29 as "A fatal hardware error" at level Warning.
    run = make_run(events=[event(WHEA, 29, FATAL_CPU, "Warning")])
    assert one(events.whea_fatal(run, T)).evidence["count"] == 1
    assert events.whea_corrected(run, T) == []


def test_whea_is_classified_by_event_id_on_a_non_english_windows():
    german_fatal = "Schwerwiegender Hardwarefehler.\n\nGemeldet von Komponente: Prozessorkern"
    german_corrected = (
        "Ein korrigierter Hardwarefehler ist aufgetreten.\n\nKomponente: Arbeitsspeicher"
    )
    run = make_run(
        events=[event(WHEA, 18, german_fatal), event(WHEA, 47, german_corrected, "Warning")]
    )
    fatal = one(events.whea_fatal(run, T))
    assert fatal.evidence["components"] == {"Processor Core": 1} and fatal.category == "cpu"
    corrected = one(events.whea_corrected(run, T))
    assert corrected.evidence["components"] == {"Memory": 1} and corrected.category == "memory"


def test_whea_with_an_unknown_id_falls_back_to_wording_then_level():
    run = make_run(
        events=[
            event(WHEA, 900, "A corrected hardware error has occurred.", "Error"),
            event(WHEA, 901, "Something else entirely.", "Error"),
            event(WHEA, 902, "Something else entirely.", "Warning"),
        ]
    )
    assert one(events.whea_corrected(run, T)).evidence["count"] == 2
    assert one(events.whea_fatal(run, T)).evidence["count"] == 1


def test_whea_informational_records_are_ignored():
    run = make_run(events=[event(WHEA, 3, "A hardware event has occurred.", "Information")])
    assert events.whea_fatal(run, T) == [] and events.whea_corrected(run, T) == []


def test_event_rules_report_no_data_when_the_log_was_not_read():
    run = make_run()  # events=None -> not collected
    for function in (
        events.whea_fatal,
        events.whea_corrected,
        events.unexpected_shutdown,
        events.bluescreen,
        events.gpu_driver_timeout,
        events.storage_io_errors,
        events.firmware_speed_limit,
    ):
        assert function(run, T) is None


def test_unexpected_shutdown_counts_only_events_without_a_stop_code():
    run = make_run(
        events=[
            event(KP, 41, BugcheckCode=0, PowerButtonTimestamp=0),
            event(KP, 41, BugcheckCode=0, PowerButtonTimestamp=133456789),
            event(KP, 41, BugcheckCode=292),  # a blue screen: not this rule's business
        ]
    )
    finding = one(events.unexpected_shutdown(run, T))
    assert finding.evidence == {**finding.evidence, "count": 2, "power_button_held": 1}
    assert finding.severity is Severity.WARNING
    many = make_run(events=[event(KP, 41, BugcheckCode=0)] * 3)
    assert one(events.unexpected_shutdown(many, T)).severity is Severity.CRITICAL
    assert events.unexpected_shutdown(make_run(events=[event(KP, 41, BugcheckCode=292)]), T) == []


def bugcheck(code: int):
    text = f"0x{code:08x} (0x0000000000000000, 0x1, 0x2, 0x3)"
    return event(
        WER,
        1001,
        f"The computer has rebooted from a bugcheck.  The bugcheck was: {text}.",
        param1=text,
    )


def test_bluescreen_reads_the_stop_code_and_explains_it():
    finding = one(events.bluescreen(make_run(events=[bugcheck(0x116)]), T))
    assert finding.error_codes == ["0x116"]
    assert "VIDEO_TDR_FAILURE" in finding.title
    assert finding.category == "gpu"
    assert finding.severity is Severity.CRITICAL  # a hardware-likely code
    driver_only = one(events.bluescreen(make_run(events=[bugcheck(0xD1)]), T))
    assert driver_only.severity is Severity.WARNING and driver_only.category == "driver"


def test_bluescreen_several_codes_point_at_hardware():
    run = make_run(events=[bugcheck(0x1A), bugcheck(0x50), bugcheck(0x3B), bugcheck(0x1A)])
    finding = one(events.bluescreen(run, T))
    assert finding.evidence["codes"] == {"0x1A": 2, "0x50": 1, "0x3B": 1}
    assert finding.category == "memory"
    assert "Several different stop codes" in finding.next_checks[0]


def test_bluescreen_reads_the_code_from_the_message_when_data_is_missing():
    message = "The computer has rebooted from a bugcheck.  The bugcheck was: 0x0000009f (0x3, 0x4, 0x5, 0x6)."
    finding = one(events.bluescreen(make_run(events=[event(WER, 1001, message)]), T))
    assert finding.error_codes == ["0x9F"]


def test_bluescreen_falls_back_to_kernel_power_and_names_suspected_drivers():
    fallback = one(events.bluescreen(make_run(events=[event(KP, 41, BugcheckCode=292)]), T))
    assert fallback.error_codes == ["0x124"]  # 292 decimal
    run = make_run(events=[bugcheck(0xD1), event(WER, 1019, SuspectedDriver="rtwlane.sys")])
    assert "rtwlane.sys" in one(events.bluescreen(run, T)).next_checks[0]


def test_bluescreen_unknown_code_and_unrecorded_code():
    unknown = one(events.bluescreen(make_run(events=[bugcheck(0xABCDE)]), T))
    assert unknown.error_codes == ["0xABCDE"] and unknown.category == "os"
    unrecorded = event(
        WER, 1006, "The computer has rebooted from a bugcheck. A dump was not saved."
    )
    assert "not recorded" in one(events.bluescreen(make_run(events=[unrecorded]), T)).title


def test_gpu_driver_timeout():
    assert events.gpu_driver_timeout(make_run(events=[]), T) == []
    finding = one(events.gpu_driver_timeout(make_run(events=[event("Display", 4101)] * 2), T))
    assert finding.evidence["count"] == 2


def test_storage_events_severity_depends_on_the_kind():
    retried = one(
        events.storage_io_errors(make_run(events=[event("disk", 153), event("storahci", 129)]), T)
    )
    assert retried.severity is Severity.WARNING
    assert set(retried.error_codes) == {"disk-153", "storahci-129"}
    bad_block = one(events.storage_io_errors(make_run(events=[event("disk", 7)]), T))
    assert bad_block.severity is Severity.CRITICAL
    ntfs = one(events.storage_io_errors(make_run(events=[event("Microsoft-Windows-Ntfs", 55)]), T))
    assert ntfs.error_codes == ["Ntfs-55"]
    assert events.storage_io_errors(make_run(events=[event("disk", 9999)]), T) == []


def test_memory_diagnostic():
    name = "Microsoft-Windows-MemoryDiagnostics-Results"
    assert events.memory_diagnostic_failed(make_run(events=[]), T) is None  # never run
    assert (
        events.memory_diagnostic_failed(make_run(events=[event(name, 1101), event(name, 1201)]), T)
        == []
    )
    assert (
        one(events.memory_diagnostic_failed(make_run(events=[event(name, 1202)]), T)).severity
        is Severity.CRITICAL
    )


def test_firmware_speed_limit():
    name = "Microsoft-Windows-Kernel-Processor-Power"
    assert events.firmware_speed_limit(make_run(events=[]), T) == []
    assert one(events.firmware_speed_limit(make_run(events=[event(name, 37)]), T)).category == "cpu"


# ----------------------------------------------------------------- storage


def disk(**overrides):
    base = {
        "name": "Test SSD",
        "media_type": "SSD",
        "health_status": "Healthy",
        "reliability": {
            "temperature_c": 40,
            "wear_pct": 5,
            "read_errors_uncorrected": 0,
            "write_errors_uncorrected": 0,
        },
    }
    reliability = {**base["reliability"], **overrides.pop("reliability", {})}
    return {**base, **overrides, "reliability": reliability}


def disks(*items, volumes=()):
    return {"physical_disks": list(items), "volumes": list(volumes)}


def test_disk_health():
    assert storage.disk_unhealthy(make_run(), T) is None
    assert storage.disk_unhealthy(make_run(disks=disks(disk())), T) == []
    warning = one(storage.disk_unhealthy(make_run(disks=disks(disk(health_status="Warning"))), T))
    assert warning.severity is Severity.WARNING
    unhealthy = one(
        storage.disk_unhealthy(make_run(disks=disks(disk(health_status="Unhealthy"))), T)
    )
    assert unhealthy.severity is Severity.CRITICAL
    errors = disk(reliability={"read_errors_uncorrected": 12})
    assert (
        one(storage.disk_unhealthy(make_run(disks=disks(errors)), T)).severity is Severity.CRITICAL
    )


def test_disk_health_handles_missing_reliability_data():
    bare = {"name": "USB stick", "health_status": "Healthy", "reliability": None}
    assert storage.disk_unhealthy(make_run(disks=disks(bare)), T) == []
    assert storage.ssd_worn(make_run(disks=disks(bare)), T) is None
    assert storage.drive_hot(make_run(disks=disks(bare)), T) is None


@pytest.mark.parametrize(
    "wear, expected", [(79, None), (80, Severity.WARNING), (95, Severity.CRITICAL)]
)
def test_ssd_wear(wear, expected):
    findings = storage.ssd_worn(make_run(disks=disks(disk(reliability={"wear_pct": wear}))), T)
    assert (findings == []) if expected is None else (one(findings).severity is expected)


def test_drive_temperature_limits_differ_for_ssd_and_hdd():
    ssd = disk(reliability={"temperature_c": 60})
    hdd = disk(name="HDD", media_type="HDD", reliability={"temperature_c": 60})
    assert storage.drive_hot(make_run(disks=disks(ssd)), T) == []
    assert one(storage.drive_hot(make_run(disks=disks(hdd)), T)).evidence["limit_c"] == 55.0
    assert one(storage.drive_hot(make_run(disks=disks(disk(reliability={"temperature_c": 74}))), T))
    # 0 means "not reported" (seen on virtual disks), not zero degrees.
    assert (
        storage.drive_hot(make_run(disks=disks(disk(reliability={"temperature_c": 0}))), T) is None
    )


def volume(letter, size_gb, free_gb, system=False):
    return {
        "drive_letter": letter,
        "size_bytes": size_gb * GB,
        "free_bytes": free_gb * GB,
        "is_system": system,
    }


def test_low_space():
    roomy = disks(volumes=[volume("C", 500, 200, True), volume("D", 1000, 150)])
    assert storage.low_space(make_run(disks=roomy), T) == []
    full_data = one(storage.low_space(make_run(disks=disks(volumes=[volume("D", 1000, 50)])), T))
    assert full_data.evidence["drive"] == "D"
    # 12 GB free on a 100 GB Windows drive is 12% - over the share line, under the 15 GB line.
    tight_system = one(
        storage.low_space(make_run(disks=disks(volumes=[volume("C", 100, 12, True)])), T)
    )
    assert tight_system.evidence["is_system"] is True
    assert storage.low_space(make_run(disks=disks(volumes=[volume("D", 100, 12)])), T) == []


def test_low_space_ignores_small_and_letterless_partitions():
    recovery = disks(volumes=[volume("", 500, 1), volume("R", 1, 0.05)])
    assert storage.low_space(make_run(disks=recovery), T) is None


# ------------------------------------------------------------------ system


def specs(modules, **extra):
    return {
        "memory": {
            "modules": modules,
            "slots_total": 4,
            "total_bytes": sum(m["capacity_bytes"] for m in modules),
        },
        **extra,
    }


def module(gb=16, rated=3600, configured=3600, part="KIT-A", kind="DDR4"):
    return {
        "capacity_bytes": gb * GB,
        "speed_mhz": rated,
        "configured_speed_mhz": configured,
        "part_number": part,
        "type": kind,
    }


def test_single_channel():
    assert system.single_channel(make_run(), T) is None
    assert system.single_channel(make_run(specs=specs([module(), module()])), T) == []
    assert (
        one(system.single_channel(make_run(specs=specs([module()])), T)).severity
        is Severity.WARNING
    )
    laptop = specs([module()], system={"type": "laptop"})
    assert one(system.single_channel(make_run(specs=laptop), T)).severity is Severity.INFO
    one_slot = specs([module()])
    one_slot["memory"]["slots_total"] = 1
    assert system.single_channel(make_run(specs=one_slot), T) == []


def test_single_module_written_as_an_object_not_a_list():
    # ConvertTo-Json collapses a one-item array; the loader must undo that.
    run = make_run(specs={"memory": {"modules": module(), "slots_total": 2}})
    assert one(system.single_channel(run, T)).evidence["modules"] == 1


def test_slow_ram_speed():
    assert system.slow_speed(make_run(specs=specs([module(), module()])), T) == []
    below = one(system.slow_speed(make_run(specs=specs([module(configured=2133)] * 2)), T))
    assert "rated for 3600" in below.title
    default = one(
        system.slow_speed(make_run(specs=specs([module(rated=0, configured=2666)] * 2)), T)
    )
    assert "default" in default.title
    ddr5 = specs([module(rated=4800, configured=4800, kind="DDR5")] * 2)
    assert one(system.slow_speed(make_run(specs=ddr5), T))
    laptop = specs([module(rated=2666, configured=2666)] * 2, system={"type": "laptop"})
    assert system.slow_speed(make_run(specs=laptop), T) == []  # laptops ship at default speed
    assert system.slow_speed(make_run(specs=specs([module(configured=0)])), T) is None


def test_mixed_modules():
    assert system.mixed_modules(make_run(specs=specs([module(), module()])), T) == []
    assert one(system.mixed_modules(make_run(specs=specs([module(), module(part="KIT-B")])), T))
    assert one(system.mixed_modules(make_run(specs=specs([module(), module(gb=8)])), T))
    assert system.mixed_modules(make_run(specs=specs([module()])), T) == []


def test_ram_and_vram_exhaustion_use_the_95th_percentile():
    brief = make_sensors(ram_used_pct=[60.0] * 99 + [99.0])  # one sample is not "full"
    assert system.ram_exhausted(make_run(sensors=brief), T) == []
    assert one(system.ram_exhausted(make_run(sensors=make_sensors(ram_used_pct=[97.0] * 30)), T))
    assert (
        system.vram_exhausted(make_run(sensors=make_sensors(gpu_vram_used_pct=[90.0] * 30)), T)
        == []
    )
    assert one(
        system.vram_exhausted(make_run(sensors=make_sensors(gpu_vram_used_pct=[99.0] * 30)), T)
    )
    assert system.ram_exhausted(make_run(), T) is None


def test_gpu_driver_missing_and_old():
    basic = {
        "gpu": [{"name": "Microsoft Basic Display Adapter", "driver_date": "2006-06-21T00:00:00Z"}]
    }
    assert one(system.gpu_driver_missing(make_run(specs=basic), T)).severity is Severity.WARNING
    assert (
        system.gpu_driver_old(make_run(specs=basic), T) is None
    )  # the fallback driver's date is meaningless
    current = {"gpu": [{"name": "RTX 3070", "driver_date": "2026-09-01T00:00:00Z"}]}
    assert system.gpu_driver_missing(make_run(specs=current), T) == []
    assert system.gpu_driver_old(make_run(specs=current), T) == []
    old = {
        "gpu": {"name": "RTX 3070", "driver_date": "2024-01-15T00:00:00Z", "driver_version": "31.0"}
    }
    assert one(system.gpu_driver_old(make_run(specs=old), T)).evidence["age_months"] == 34


def test_power_plan():
    assert system.power_saver_plan(make_run(), T) is None
    balanced = {"power_plan": "Balanced", "power_plan_guid": "381b4222-f694-41f0-9685-ff5bb260df2e"}
    assert system.power_saver_plan(make_run(specs=balanced), T) == []
    # Matched by GUID, so it works on a non-English Windows too.
    saver = {
        "power_plan": "Energiesparmodus",
        "power_plan_guid": "A1841308-3541-4FAB-BC81-F71556F20B4A",
    }
    assert one(system.power_saver_plan(make_run(specs=saver), T)).code == "os.power_saver_plan"


def test_battery_wear():
    assert system.battery_worn(make_run(specs={"battery": None}), T) is None
    fresh = {"battery": {"design_capacity_mwh": 80000, "full_charge_capacity_mwh": 76000}}
    assert system.battery_worn(make_run(specs=fresh), T) == []
    worn = {"battery": {"design_capacity_mwh": 80000, "full_charge_capacity_mwh": 40000}}
    assert one(system.battery_worn(make_run(specs=worn), T)).evidence["capacity_lost_pct"] == 50.0
    assert system.battery_worn(make_run(specs={"battery": {"design_capacity_mwh": 0}}), T) is None


def test_every_finding_has_text_a_person_can_act_on():
    from pcdoctor_analysis import synth
    from pcdoctor_analysis.analyze import analyze_run_dir

    seen = set()
    for sample in synth.build_all():
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            sample.write(folder)
            for finding in analyze_run_dir(folder).findings:
                seen.add(finding.code)
                assert len(finding.title) > 10 and len(finding.summary) > 60
                assert finding.next_checks, finding.code
                assert "\n" not in finding.title
    assert len(seen) >= 20
