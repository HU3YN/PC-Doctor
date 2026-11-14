"""Regression tests for bugs the fuzz tests in fuzz/ found (2026-11-14).

Each test is the smallest input that showed the bug. See fuzz/README.md.
"""

from __future__ import annotations

import io
import json

import pytest

from pcdoctor_analysis import analyze_run_dir, load_run_dir
from pcdoctor_analysis.presentmon import (
    PresentMonError,
    compute_frame_stats,
    parse_presentmon_csv,
)
from pcdoctor_analysis.rules import storage, system
from pcdoctor_analysis.sensors import parse_sensors_csv

HUGE_FIELD = '"' + "a" * 140_000 + '"'  # over the csv module's 131072 field limit


def crashed_checks(result) -> list[str]:
    return [note for note in result.notes if " failed: " in note]


def test_presentmon_field_over_csv_limit_is_a_presentmon_error(tmp_path):
    path = tmp_path / "presentmon.csv"
    path.write_text(f"MsBetweenPresents\n{HUGE_FIELD}\n")
    with pytest.raises(PresentMonError):
        parse_presentmon_csv(path)


def test_sensors_field_over_csv_limit_is_a_value_error(tmp_path):
    path = tmp_path / "sensors.csv"
    path.write_text(f"elapsed_s,cpu_temp_c\n0,{HUGE_FIELD}\n")
    with pytest.raises(ValueError):
        parse_sensors_csv(path)


def test_run_with_damaged_csv_files_is_a_note_not_a_crash(tmp_path):
    (tmp_path / "presentmon.csv").write_text(f"MsBetweenPresents\n{HUGE_FIELD}\n")
    (tmp_path / "sensors.csv").write_text(f"elapsed_s\n{HUGE_FIELD}\n")
    run = load_run_dir(tmp_path)
    assert run.frames is None and run.sensors is None
    assert any(note.startswith("Frame times:") for note in run.notes)
    assert any(note.startswith("Sensors:") for note in run.notes)


def test_sensors_infinite_elapsed_time_is_dropped(tmp_path):
    path = tmp_path / "sensors.csv"
    path.write_text("elapsed_s,cpu_temp_c\ninf,50\n-inf,51\n1e999,52\n")
    data = parse_sensors_csv(path)
    assert data.elapsed_s == [0.0, 1.0, 2.0]  # the row number stands in


def test_sensors_duplicate_column_has_one_value_per_sample(tmp_path):
    path = tmp_path / "sensors.csv"
    path.write_text("elapsed_s,gpu_temp_c,gpu_temp_c\n0,50,60\n")
    data = parse_sensors_csv(path)
    assert data.samples == 1
    assert len(data.series["gpu_temp_c"]) == 1


@pytest.mark.parametrize("module", [storage, system])
@pytest.mark.parametrize(
    "value",
    [pytest.param(10**400, id="400-digit-int"), "1e999", "-inf", "nan", float("inf")],
)
def test_rule_numbers_are_finite_or_none(module, value):
    assert module._number(value) is None


def test_huge_drive_temperature_does_not_crash_the_check(tmp_path):
    disks = {"physical_disks": [{"name": "SSD", "reliability": {"temperature_c": 10**400}}]}
    (tmp_path / "disks.json").write_text(json.dumps(disks))
    result = analyze_run_dir(tmp_path)
    assert crashed_checks(result) == []


def test_infinite_volume_size_stays_out_of_the_result(tmp_path):
    disks = {"volumes": [{"drive_letter": "C", "size_bytes": "1e999", "free_bytes": "1"}]}
    (tmp_path / "disks.json").write_text(json.dumps(disks))
    result = analyze_run_dir(tmp_path)
    assert crashed_checks(result) == []
    json.dumps(result.to_dict(), allow_nan=False)


@pytest.mark.parametrize("bad_id", [[], {}, [41], True, "41"])
def test_event_id_that_is_not_a_number_does_not_crash_the_checks(tmp_path, bad_id):
    events = {
        "window_days": 30,
        "events": [
            {
                "time": "2026-10-11T13:12:00Z",
                "provider": provider,
                "id": bad_id,
                "level": "Error",
                "message": "A fatal hardware error has occurred.",
            }
            for provider in ("Microsoft-Windows-WHEA-Logger", "disk", "Ntfs")
        ],
    }
    (tmp_path / "events.json").write_text(json.dumps(events))
    result = analyze_run_dir(tmp_path)
    assert crashed_checks(result) == []
    json.dumps(result.to_dict(), allow_nan=False)


@pytest.mark.parametrize("frame_time", ["5e-324", "1E-310", "1e308"])
def test_absurd_frame_times_are_skipped(frame_time):
    # 1000 / 5e-324 is inf, and two frames of 1e308 ms sum to inf: the frame
    # statistics then held inf and the result could not be stored as JSON.
    text = f"Application,MsBetweenPresents\ngame.exe,{frame_time}\ngame.exe,16.6\ngame.exe,{frame_time}\n"
    data = parse_presentmon_csv(io.StringIO(text, newline=""))
    assert data.frame_times_ms == [16.6]
    json.dumps(compute_frame_stats(data).to_dict(), allow_nan=False)
