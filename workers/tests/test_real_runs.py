"""Lessons from the first run on real hardware (the owner's PC, 2026-11-15)."""

from __future__ import annotations

import re

from pcdoctor_analysis.rules import events
from pcdoctor_analysis.stopcodes import STOP_CODES


def test_no_double_full_stops_in_any_stop_code_summary():
    # The real 0x9F blue screen read "...shutting down.. Usual causes".
    for code, entry in STOP_CODES.items():
        line = f"{entry.hex} {entry.name} - {events._clause(entry.meaning)}"
        summary = f"Windows blue-screened 1 time(s) in 30 days: {line}."
        summary += " Usual causes: " + "; ".join(events._clause(c) for c in entry.causes) + "."
        assert ".." not in summary and ".;" not in summary, (hex(code), summary)
        assert re.search(r"[^.]\.$", summary)


# A quick run shaped like the owner's real one: a disk I/O retry, then the
# blue-screen records Windows writes when it restarts (made-up values).
DISK_RETRY = {
    "time": "2026-10-26T00:04:54Z",
    "provider": "disk",
    "id": 153,
    "level": "Warning",
    "log": "System",
    "message": "The IO operation at logical block address 0x4b20 for Disk 3 (PDO name: "
    "\\Device\\000000e1) was retried.",
    "data": {},
}


def crash_records(time: str) -> list[dict]:
    return [
        {
            "time": time,
            "provider": "Microsoft-Windows-Kernel-Power",
            "id": 41,
            "level": "Critical",
            "log": "System",
            "message": "The system has rebooted without cleanly shutting down first.",
            "data": {"BugcheckCode": "159", "BugcheckParameter1": "0x3"},
        }
    ]


def run_with(tmp_path, events: list[dict], disks: list[dict] | None = None):
    import json

    from pcdoctor_analysis import analyze_run_dir, synth

    synth.build("healthy").write(tmp_path)
    folder = tmp_path if (tmp_path / "manifest.json").exists() else next(tmp_path.iterdir())
    document = json.loads((folder / "events.json").read_text(encoding="utf-8-sig"))
    document["events"] = events
    (folder / "events.json").write_text(json.dumps(document), encoding="utf-8")
    if disks is not None:
        stored = json.loads((folder / "disks.json").read_text(encoding="utf-8-sig"))
        stored["physical_disks"] = disks
        (folder / "disks.json").write_text(json.dumps(stored), encoding="utf-8")
    return {f.code: f for f in analyze_run_dir(folder).findings}


def test_a_disk_error_minutes_before_a_blue_screen_is_called_possibly_one_incident(tmp_path):
    found = run_with(tmp_path, [DISK_RETRY, *crash_records("2026-10-26T00:12:48Z")])
    disk, crash = found["storage.io_errors"], found["stability.bluescreen"]
    for finding in (disk, crash):
        assert "possibly one incident" in finding.summary
        assert "restarts" in finding.summary  # the record's time is the restart, said so
    assert disk.evidence["minutes_before_a_blue_screen"] == 7
    assert crash.evidence["minutes_after_a_disk_error"] == 7
    assert crash.next_checks[0].startswith("Check the disk error")


def test_far_apart_or_in_the_wrong_order_is_not_linked(tmp_path):
    later = run_with(tmp_path / "a", [DISK_RETRY, *crash_records("2026-10-26T03:00:00Z")])
    assert "possibly one incident" not in later["storage.io_errors"].summary
    before = run_with(tmp_path / "b", [*crash_records("2026-10-25T23:50:00Z"), DISK_RETRY])
    assert before["storage.io_errors"].evidence["minutes_before_a_blue_screen"] is None


def disk(name: str, number: int | None) -> dict:
    return {
        "name": name,
        "media_type": "SSD",
        "bus_type": "NVMe",
        "health_status": "Healthy",
        "operational_status": "OK",
        "number": number,
        "reliability": {},
    }


def test_the_disk_number_names_the_drive(tmp_path):
    three = [disk("Drive A", 0), disk("Drive B", 1), disk("Drive C", 2)]
    absent = run_with(tmp_path / "a", [DISK_RETRY], three)["storage.io_errors"]
    assert "Disk 3 is none of the drives listed" in absent.summary
    assert absent.evidence["disk_numbers"] == [3]
    present = run_with(tmp_path / "b", [DISK_RETRY], [*three, disk("Drive D", 3)])
    assert "Disk 3 is the Drive D" in present["storage.io_errors"].summary
    # A run from before disk numbers were recorded (like the owner's first one).
    old = run_with(tmp_path / "c", [DISK_RETRY])["storage.io_errors"]
    assert "does not record disk numbers" in old.summary


def idle_capture_run(tmp_path, gpu_load: str):
    """The healthy sample capture without frame times and with the given GPU
    load - like the owner's first capture, made with nothing running."""
    from pcdoctor_analysis import synth

    synth.build("healthy").write(tmp_path)
    folder = tmp_path if (tmp_path / "manifest.json").exists() else next(tmp_path.iterdir())
    (folder / "presentmon.csv").unlink()
    lines = (folder / "sensors.csv").read_text(encoding="utf-8").splitlines()
    column = lines[0].split(",").index("gpu_load_pct")
    rows = [lines[0]]
    for line in lines[1:]:
        cells = line.split(",")
        cells[column] = gpu_load
        rows.append(",".join(cells))
    (folder / "sensors.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return folder


def test_an_idle_capture_judges_no_performance_and_says_why(tmp_path):
    from pcdoctor_analysis import analyze_run_dir

    result = analyze_run_dir(idle_capture_run(tmp_path, "3"))
    status = {c.code: c.status for c in result.checks}
    assert status["performance.gpu_limited"] == "no_data"
    assert status["performance.cpu_limited"] == "no_data"
    assert any("mostly idle during the capture" in note for note in result.notes)


def test_a_busy_card_without_frame_times_is_still_judged(tmp_path):
    from pcdoctor_analysis import analyze_run_dir

    result = analyze_run_dir(idle_capture_run(tmp_path, "98"))
    status = {c.code: c.status for c in result.checks}
    assert status["performance.gpu_limited"] == "found"
    assert not any("idle" in note for note in result.notes)
