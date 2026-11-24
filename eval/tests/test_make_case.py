"""make_case.py: a run zip becomes a labeled case, and bad zips are refused."""

import json
import zipfile

import pytest
from pcdoctor_analysis import synth

import make_case


def build_zip(path, files, prefix=""):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(prefix + name, content)
    return path


@pytest.fixture
def disk_files():
    return dict(synth.failing_disk().files)


@pytest.fixture
def cases(tmp_path):
    return tmp_path / "cases"


def run(zip_path, cases, *extra, name="case-one", expect=("storage.io_errors",)):
    argv = [str(zip_path), f"--name={name}", "--cases-dir", str(cases)]
    for code in expect:
        argv += ["--expect", code]
    return make_case.main(argv + list(extra))


def test_good_zip_writes_case_with_label(tmp_path, cases, disk_files, capsys):
    zip_path = build_zip(tmp_path / "run.zip", disk_files)
    code = run(
        zip_path,
        cases,
        "--absent",
        "thermal.cpu_hot",
        "--note",
        "USB-C drive attached",
        "--source",
        "owner-pc",
    )
    assert code == 0
    folder = cases / "case-one"
    assert sorted(p.name for p in folder.iterdir()) == sorted([*disk_files, "label.json"])
    label = json.loads((folder / "label.json").read_text())
    assert label["expected"] == ["storage.io_errors"]
    assert label["must_not"] == ["thermal.cpu_hot"]
    assert label["description"] == "USB-C drive attached"
    assert label["machine"] == "owner-pc"
    assert label["note"] == "USB-C drive attached"
    out = capsys.readouterr().out
    assert "fires" in out and "storage.io_errors" in out


def test_label_is_read_by_run_eval(tmp_path, cases, disk_files, monkeypatch):
    import run_eval

    run(build_zip(tmp_path / "run.zip", disk_files), cases)
    monkeypatch.setattr(run_eval, "CASES", cases)
    [(name, _, label)] = run_eval.real_cases()
    assert name == "case-one" and label["expected"] == ["storage.io_errors"]


def test_miss_is_reported_not_failed(tmp_path, cases, capsys):
    zip_path = build_zip(tmp_path / "run.zip", synth.healthy().files)
    assert run(zip_path, cases, expect=("thermal.cpu_hot",)) == 0
    assert "MISSED" in capsys.readouterr().out


def test_nested_folder_zip_accepted(tmp_path, cases, disk_files):
    zip_path = build_zip(tmp_path / "run.zip", disk_files, prefix="PCDoctor-run-1/")
    assert run(zip_path, cases) == 0
    assert (cases / "case-one" / "manifest.json").is_file()


@pytest.mark.parametrize(
    "entry", ["../evil.json", "/abs/manifest.json", "a/../../manifest.json", "C:/manifest.json"]
)
def test_zip_slip_refused(tmp_path, cases, disk_files, entry, capsys):
    zip_path = build_zip(tmp_path / "run.zip", disk_files)
    with zipfile.ZipFile(zip_path, "a") as archive:
        archive.writestr(entry, "{}")
    assert run(zip_path, cases) == 2
    assert not (cases / "case-one").exists()
    assert "Refused" in capsys.readouterr().err


def test_unknown_file_refused(tmp_path, cases, disk_files):
    zip_path = build_zip(tmp_path / "run.zip", {**disk_files, "notes.txt": "hi"})
    assert run(zip_path, cases) == 2
    assert not cases.exists() or not (cases / "case-one").exists()


def test_deep_or_mixed_layout_refused(tmp_path, cases, disk_files):
    zip_path = build_zip(tmp_path / "run.zip", disk_files, prefix="a/b/")
    assert run(zip_path, cases) == 2
    mixed = build_zip(tmp_path / "mixed.zip", disk_files)
    with zipfile.ZipFile(mixed, "a") as archive:
        archive.writestr("sub/collector.log", "x")
    assert run(mixed, cases) == 2


def test_not_a_zip_and_oversize_refused(tmp_path, cases, disk_files, monkeypatch):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    assert run(bad, cases) == 2
    good = build_zip(tmp_path / "run.zip", disk_files)
    monkeypatch.setattr(make_case, "MAX_FILE_BYTES", 10)
    assert run(good, cases) == 2


def test_unknown_rule_code_refused(tmp_path, cases, disk_files, capsys):
    zip_path = build_zip(tmp_path / "run.zip", disk_files)
    assert run(zip_path, cases, expect=("storage.nonsense",)) == 2
    assert "unknown finding code" in capsys.readouterr().err
    assert run(zip_path, cases, "--absent", "nope.nope") == 2
    assert not (cases / "case-one").exists()


def test_needs_a_code(tmp_path, cases, disk_files):
    zip_path = build_zip(tmp_path / "run.zip", disk_files)
    assert run(zip_path, cases, expect=()) == 2


@pytest.mark.parametrize(
    "text",
    [
        r"Dump at C:\\Users\\Alice\\x.dmp",
        "mail alice@example.com about it",
        "Disk serial number: WD-WCC4E1234567",
    ],
)
def test_privacy_hit_refused_unless_forced(tmp_path, cases, disk_files, text, capsys):
    files = {**disk_files, "collector.log": f"line one\n{text}\n"}
    zip_path = build_zip(tmp_path / "run.zip", files)
    assert run(zip_path, cases) == 2
    err = capsys.readouterr().err
    assert "collector.log:2" in err and "line one" not in err
    assert not (cases / "case-one").exists()
    assert run(zip_path, cases, "--force") == 0
    assert (cases / "case-one" / "label.json").is_file()


def test_scrubbed_text_passes_privacy(tmp_path, cases, disk_files):
    log = "C:\\Users\\<user>\\x.dmp serial number: <removed> C:\\Users\\Public\\a"
    zip_path = build_zip(tmp_path / "run.zip", {**disk_files, "collector.log": log})
    assert run(zip_path, cases) == 0


def test_existing_case_not_overwritten(tmp_path, cases, disk_files, capsys):
    zip_path = build_zip(tmp_path / "run.zip", disk_files)
    assert run(zip_path, cases, "--note", "first") == 0
    assert run(zip_path, cases, "--note", "second") == 2
    label = json.loads((cases / "case-one" / "label.json").read_text())
    assert label["note"] == "first"
    assert run(zip_path, cases, "--note", "second", "--force") == 0
    label = json.loads((cases / "case-one" / "label.json").read_text())
    assert label["note"] == "second"
    assert [p.name for p in cases.iterdir()] == ["case-one"]  # no staging leftovers


@pytest.mark.parametrize("name", ["../x", "A B", "", "-x"])
def test_bad_case_name_refused(tmp_path, cases, disk_files, name):
    zip_path = build_zip(tmp_path / "run.zip", disk_files)
    assert run(zip_path, cases, name=name) == 2


def test_run_files_match_the_server():
    from pcdoctor_api.services.ingest import RUN_FILES

    assert make_case.RUN_FILES == RUN_FILES
