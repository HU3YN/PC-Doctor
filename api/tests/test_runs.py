from __future__ import annotations

import io
import zipfile

import pytest
from pcdoctor_analysis import RULES_VERSION, synth

from pcdoctor_api.config import get_settings


def zip_of(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def post(client, data: bytes, name: str = "run.zip"):
    return client.post("/api/runs", files={"file": (name, data, "application/octet-stream")})


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["rules_version"] == RULES_VERSION


def test_upload_stores_the_run_its_findings_and_the_file(client, upload):
    body = upload("cpu_overheat", label="bench 3")
    assert body["duplicate"] is False
    run = body["run"]
    assert run["label"] == "bench 3" and run["verdict"] == "warning"
    assert run["cpu"].startswith("Intel") and run["avg_fps"] > 50 and run["mode"] == "capture"

    detail = client.get(f"/api/runs/{run['id']}").json()
    codes = [f["code"] for f in detail["findings"]]
    assert sorted(codes) == sorted(synth.build("cpu_overheat").expected)
    assert detail["findings"][0]["code"] == "thermal.cpu_hot"  # stored in the analysed order
    assert detail["has_frames"] and detail["has_sensors"] and not detail["rules_outdated"]
    assert detail["frame_stats"]["frames"] > 1000
    assert {c["status"] for c in detail["checks"]} <= {"found", "passed", "no_data"}
    assert (get_settings().runs_dir / f"{run['id']}.zip").is_file()


def test_upload_response_codes_new_is_201_duplicate_is_200(client):
    data = synth.build("healthy").zip_bytes()
    first, second = post(client, data), post(client, data)
    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json()["duplicate"] is True
    assert second.json()["run"]["id"] == first.json()["run"]["id"]
    assert client.get("/api/runs").json()["total"] == 1


def test_series_is_small_enough_to_chart_and_keeps_the_spikes(client, upload):
    run_id = upload("stutter_vram")["run"]["id"]
    series = client.get(f"/api/runs/{run_id}/series").json()
    frames = series["frames"]
    assert 100 < len(frames["t"]) <= 1200
    assert len(frames["t"]) == len(frames["avg_ms"]) == len(frames["max_ms"])
    assert max(frames["max_ms"]) > 100  # the hitches survive downsampling
    assert len(series["sensors"]["t"]) == len(series["sensors"]["gpu_vram_used_pct"]) == 120


def test_quick_run_has_no_series(client, upload):
    run_id = upload("failing_disk")["run"]["id"]
    detail = client.get(f"/api/runs/{run_id}").json()
    assert not detail["has_frames"] and detail["frame_stats"] is None and detail["mode"] == "quick"
    assert client.get(f"/api/runs/{run_id}/series").json() == {}


def test_a_bare_presentmon_csv_is_accepted(client):
    csv = synth.build("healthy").files["presentmon.csv"].encode()
    response = post(client, csv, "capture.csv")
    assert response.status_code == 201
    detail = client.get(f"/api/runs/{response.json()['run']['id']}").json()
    assert detail["avg_fps"] > 100 and detail["mode"] == "capture"
    assert any("manifest.json is missing" in note for note in detail["analysis_notes"])


def test_a_zipped_folder_is_accepted_and_unknown_files_are_dropped(client):
    sample = synth.build("power_loss")
    files = {f"PCDoctor-run-20261101/{name}": text.encode() for name, text in sample.files.items()}
    files["PCDoctor-run-20261101/passwords.txt"] = b"not part of a run"
    files["PCDoctor-run-20261101/deep/er/specs.json"] = b"{}"  # too deep: ignored
    response = post(client, zip_of(files))
    assert response.status_code == 201
    run_id = response.json()["run"]["id"]
    with zipfile.ZipFile(get_settings().runs_dir / f"{run_id}.zip") as stored:
        assert sorted(stored.namelist()) == sorted(sample.files)  # only known files, flat


def test_path_traversal_names_cannot_escape(client, tmp_path):
    sample = synth.build("healthy")
    files = {name: text.encode() for name, text in sample.files.items() if name != "presentmon.csv"}
    files["../../evil.json"] = b"{}"
    files["/etc/cron.d/manifest.json"] = b"{}"
    assert post(client, zip_of(files)).status_code == 201
    assert not (tmp_path / "evil.json").exists()
    assert not list(tmp_path.rglob("evil.json"))


@pytest.mark.parametrize(
    "data, message",
    [
        (b"", "empty"),
        (b"just some text", "not a PC Doctor run"),
        (b"PK\x03\x04 broken", "damaged"),
        (zip_of({"readme.txt": b"hello"}), "No PC Doctor files"),
    ],
)
def test_bad_uploads_get_a_clear_400(client, data, message):
    response = post(client, data)
    assert response.status_code == 400 and message in response.json()["detail"]
    assert client.get("/api/runs").json()["total"] == 0
    assert not list(get_settings().runs_dir.glob("*.zip"))


def test_upload_larger_than_the_limit_is_refused(client, monkeypatch):
    monkeypatch.setenv("PCDOCTOR_MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    response = post(client, b"x" * (1024 * 1024 + 10))
    assert response.status_code == 413


def test_a_zip_that_unpacks_too_large_is_refused(client, monkeypatch):
    monkeypatch.setenv("PCDOCTOR_MAX_UNPACKED_MB", "1")
    get_settings.cache_clear()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("presentmon.csv", b"0" * (3 * 1024 * 1024))  # compresses to almost nothing
    response = post(client, buffer.getvalue())
    assert response.status_code == 400 and "over the limit" in response.json()["detail"]


def test_list_filter_and_order(client, upload):
    upload("healthy")
    upload("whea_bluescreens")
    upload("cpu_overheat")
    everything = client.get("/api/runs").json()
    assert everything["total"] == 3
    stamps = [r["created_at"] for r in everything["items"]]
    assert stamps == sorted(stamps, reverse=True)
    critical = client.get("/api/runs?verdict=critical").json()
    assert critical["total"] == 1 and "fatal hardware" in critical["items"][0]["headline"]
    assert client.get("/api/runs?verdict=nonsense").status_code == 422
    assert len(client.get("/api/runs?limit=2").json()["items"]) == 2


def test_times_come_back_with_a_utc_offset(client, upload):
    run = upload("healthy")["run"]
    assert run["captured_at"].startswith("2026-11-01T18:00:00")
    assert run["captured_at"].endswith(("Z", "+00:00"))
    assert run["created_at"].endswith(("Z", "+00:00"))


def test_patch_label_and_notes(client, upload):
    run_id = upload("healthy")["run"]["id"]
    body = client.patch(
        f"/api/runs/{run_id}", json={"label": "  after repaste ", "notes": "ok"}
    ).json()
    assert body["label"] == "after repaste" and body["notes"] == "ok"
    assert (
        client.patch(f"/api/runs/{run_id}", json={"notes": "only notes"}).json()["label"]
        == "after repaste"
    )
    assert client.patch(f"/api/runs/{run_id}", json={"label": "x" * 201}).status_code == 422


def test_reanalyze_download_and_delete(client, upload):
    run_id = upload("bad_ram")["run"]["id"]
    again = client.post(f"/api/runs/{run_id}/reanalyze")
    assert again.status_code == 200 and len(again.json()["findings"]) == 4  # replaced, not doubled

    download = client.get(f"/api/runs/{run_id}/download")
    assert download.status_code == 200 and download.content[:2] == b"PK"

    assert client.delete(f"/api/runs/{run_id}").status_code == 204
    assert client.get(f"/api/runs/{run_id}").status_code == 404
    assert not list(get_settings().runs_dir.glob("*.zip"))
    assert client.get("/api/stats?include_demo=true").json()["findings_by_code"] == {}  # cascade


def test_reanalyze_reports_a_missing_file_instead_of_crashing(client, upload):
    run_id = upload("healthy")["run"]["id"]
    (get_settings().runs_dir / f"{run_id}.zip").unlink()
    assert client.post(f"/api/runs/{run_id}/reanalyze").status_code == 409
    assert client.get(f"/api/runs/{run_id}/download").status_code == 404


def test_unknown_run_is_404(client):
    for method, path in [
        ("get", "/api/runs/nope"),
        ("get", "/api/runs/nope/series"),
        ("delete", "/api/runs/nope"),
        ("post", "/api/runs/nope/reanalyze"),
    ]:
        assert getattr(client, method)(path).status_code == 404
