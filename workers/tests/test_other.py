from __future__ import annotations

import json

import pytest

from pcdoctor_analysis import RULES_VERSION, analyze_run_dir, synth
from pcdoctor_analysis.cli import main
from pcdoctor_analysis.loader import load_run_dir, parse_time
from pcdoctor_analysis.sensors import parse_sensors_csv, summarize
from pcdoctor_analysis.series import frame_series, sensor_series
from pcdoctor_analysis.stopcodes import STOP_CODES, extract_codes, lookup, parse_code, search

from .conftest import make_frames, make_sensors

# ------------------------------------------------------------- stop codes


@pytest.mark.parametrize(
    "text, expected",
    [
        ("0x00000124", 0x124),
        ("0x124", 0x124),
        ("124", 0x124),
        ("0X1a", 0x1A),
        ("c000021a", 0xC000021A),
        (292, 292),
        ("stop code 0x0000007E (0xffff...)", 0x7E),
        ("", None),
        ("hello", None),
        (None, None),
    ],
)
def test_parse_code(text, expected):
    assert parse_code(text) == expected


def test_lookup_by_number_and_by_name():
    assert lookup("0x124").name == "WHEA_UNCORRECTABLE_ERROR"
    assert lookup("whea uncorrectable error").code == 0x124
    assert lookup("0xDEAD") is None


def test_every_curated_code_has_guidance_and_a_real_category():
    from pcdoctor_analysis.model import CATEGORIES

    curated = [c for c in STOP_CODES.values() if c.meaning]
    assert len(curated) >= 55
    for entry in curated:
        assert entry.category in CATEGORIES
        assert entry.causes and entry.checks, entry.name
        assert entry.name == entry.name.upper()


def test_search():
    assert search("124")[0].code == 0x124
    assert {c.code for c in search("video tdr")} == {0x116, 0x117}
    assert search("zzzz") == []
    assert len(search("")) == 20  # browsing: the curated list


def test_extract_codes_from_free_text():
    assert extract_codes("BSOD 0x00000124 then 0x1a, again 0x124") == ["0x124", "0x1A"]
    assert extract_codes("no codes, fan 0xZZ") == []


# ---------------------------------------------------------------- sensors


def test_sensor_csv_parsing(tmp_path):
    path = tmp_path / "sensors.csv"
    path.write_text(
        "elapsed_s,cpu_temp_c,gpu_load_pct,unknown_column,gpu_power_w\n"
        "0,55.5,98,1,\n"
        '1,"56,5",99,1,\n'  # decimal comma
        "2,255,150,1,\n"  # glitches: out of range
        "3,,97,1,\n",
        encoding="utf-8",
    )
    data = parse_sensors_csv(path)
    assert data.series["cpu_temp_c"] == [55.5, 56.5, None, None]
    assert data.series["gpu_load_pct"] == [98.0, 99.0, None, 97.0]
    assert "unknown_column" not in data.series
    assert "gpu_power_w" not in data.series  # a column with no readings is dropped
    assert len(data.notes) == 2
    stats = summarize(data)
    assert stats["cpu_temp_c"]["max"] == 56.5 and stats["cpu_temp_c"]["unit"] == "°C"


# ----------------------------------------------------------------- series


def test_frame_series_keeps_the_worst_frame_of_every_bucket():
    frames = [10.0] * 5000
    frames[2500] = 300.0
    series = frame_series(make_frames(frames), max_points=100)
    assert len(series["t"]) <= 100
    assert max(series["max_ms"]) == 300.0
    assert max(series["avg_ms"]) < 300.0


def test_sensor_series_keeps_gaps_and_peaks():
    data = make_sensors(cpu_temp_c=[50.0, None, 90.0, 60.0])
    assert sensor_series(data)["cpu_temp_c"] == [50.0, None, 90.0, 60.0]
    assert sensor_series(data, max_points=2)["cpu_temp_c"] == [50.0, 90.0]


# ----------------------------------------------------------------- loader


def test_parse_time():
    assert parse_time("2026-11-01T18:00:00Z").isoformat() == "2026-11-01T18:00:00+00:00"
    assert parse_time("2026-11-01T18:00:00").tzinfo is not None
    assert parse_time("yesterday") is None and parse_time(None) is None


def test_loader_survives_missing_and_damaged_files(tmp_path):
    (tmp_path / "specs.json").write_text("{ not json", encoding="utf-8")
    (tmp_path / "events.json").write_bytes(
        b"\xef\xbb\xbf" + json.dumps({"events": {"provider": "disk", "id": 7}}).encode()
    )
    (tmp_path / "presentmon.csv").write_text("Application,Nothing\n", encoding="utf-8")
    run = load_run_dir(tmp_path)
    assert run.specs["cpu"] == [] and run.frames is None
    assert run.events_collected and len(run.events) == 1  # BOM handled, object -> list
    notes = " ".join(run.notes)
    assert "manifest.json is missing" in notes and "specs.json could not be read" in notes
    assert "Frame times:" in notes
    result = analyze_run_dir(tmp_path)  # and the analysis still completes
    assert [f.code for f in result.findings] == ["storage.io_errors"]


def test_loader_warns_about_a_newer_run_format(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps({"schema_version": 99, "warnings": "no admin"})
    )
    notes = " ".join(load_run_dir(tmp_path).notes)
    assert "format version 99" in notes and "Collector: no admin" in notes


def test_loader_rejects_a_missing_folder(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_run_dir(tmp_path / "nope")


# ------------------------------------------------------- synthetic samples


@pytest.mark.parametrize("name", list(synth.SCENARIOS))
def test_each_sample_run_gets_exactly_its_expected_diagnosis(name, tmp_path):
    sample = synth.build(name)
    sample.write(tmp_path)
    result = analyze_run_dir(tmp_path)
    assert sorted(f.code for f in result.findings) == sorted(sample.expected)
    assert result.rules_version == RULES_VERSION
    assert result.notes == []
    json.dumps(result.to_dict())  # the whole result must be plain JSON


def test_sample_runs_are_deterministic_and_marked_synthetic():
    first, second = synth.build("cpu_overheat"), synth.build("cpu_overheat")
    assert first.files == second.files
    assert first.zip_bytes() == second.zip_bytes()
    assert json.loads(first.files["manifest.json"])["synthetic"] is True


def test_healthy_sample_has_a_clean_verdict(tmp_path):
    synth.build("healthy").write(tmp_path)
    result = analyze_run_dir(tmp_path)
    assert result.verdict == "ok" and result.headline.startswith("No faults found")
    assert result.device["cpu"].startswith("AMD Ryzen 7") and result.device["ram_gb"] == 32
    assert result.counts == {"critical": 0, "warning": 0, "info": 1}


def test_overheat_headline_is_the_cause_not_the_stutter(tmp_path):
    synth.build("cpu_overheat").write(tmp_path)
    assert analyze_run_dir(tmp_path).headline.startswith("CPU running hot")


# -------------------------------------------------------------------- cli


def test_cli_run_report_json_frames_and_rules(tmp_path, capsys):
    synth.build("stutter_vram").write(tmp_path)
    assert main([str(tmp_path)]) == 0
    text = capsys.readouterr().out
    assert "WARNING: Video memory was full" in text and "Passed (" in text
    assert main([str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "warning"
    assert main(["frames", str(tmp_path / "presentmon.csv")]) == 0
    out = capsys.readouterr().out
    assert "Average FPS" in out and "1% low FPS" in out and "Spikes" in out
    assert main(["rules"]) == 0
    assert "fault types" in capsys.readouterr().out
    assert main([str(tmp_path / "missing")]) == 2
    assert main(["frames", str(tmp_path / "specs.json")]) == 2


def test_hostile_json_is_skipped_not_fatal(tmp_path):
    """Found by fuzzing: a number thousands of digits long, or very deep
    nesting, used to crash the loader instead of becoming a note."""
    from pcdoctor_analysis import analyze_run_dir

    (tmp_path / "manifest.json").write_text('{"a": ' + "9" * 5000 + "}")
    (tmp_path / "specs.json").write_text("[" * 100_000 + "]" * 100_000)
    result = analyze_run_dir(tmp_path)
    assert any("manifest.json could not be read" in note for note in result.notes)
    assert any("specs.json could not be read" in note for note in result.notes)
