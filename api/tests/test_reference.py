from __future__ import annotations

from pcdoctor_analysis import synth

from pcdoctor_api.config import get_settings

from .conftest import entry


def test_meta_lists_form_options_and_every_rule(client):
    meta = client.get("/api/meta").json()
    assert "thermal" in meta["categories"] and "fixed" in meta["statuses"]
    assert "gaming_pc" in meta["device_types"]
    assert len(meta["rules"]) >= 29
    assert {"code", "category", "title", "detects", "needs"} <= set(meta["rules"][0])


def test_stop_code_lookup_and_search(client):
    assert client.get("/api/stopcodes?q=124").json()[0]["name"] == "WHEA_UNCORRECTABLE_ERROR"
    assert client.get("/api/stopcodes?q=video tdr").json()[0]["category"] == "gpu"
    assert len(client.get("/api/stopcodes").json()) == 25
    one = client.get("/api/stopcodes/0x0000001A").json()
    assert one["hex"] == "0x1A" and one["checks"] and one["cases"] == []
    assert client.get("/api/stopcodes/0xDEAD").status_code == 404


def test_stop_code_page_shows_where_it_was_seen_before(client):
    client.post("/api/worklog", json=entry(title="Bad stick in A2", error_codes=["0x1a"]))
    client.post(
        "/api/worklog", json=entry(title="Mentions it in text", symptoms="got 0x0000001A twice")
    )
    client.post("/api/worklog", json=entry(title="Different code", error_codes=["0x50"]))
    cases = client.get("/api/stopcodes/0x1A").json()["cases"]
    assert {c["entry"]["title"] for c in cases} == {"Bad stick in A2", "Mentions it in text"}


def test_demo_data_loads_once_and_clears_without_touching_real_data(client):
    mine = client.post("/api/worklog", json=entry(title="My real job")).json()
    assert client.post("/api/demo").json() == {"runs": len(synth.SCENARIOS), "work_log": 7}
    assert client.post("/api/demo").json() == {"runs": 0, "work_log": 0}  # no duplicates
    assert client.get("/api/runs").json()["total"] == len(synth.SCENARIOS)
    assert all(r["is_demo"] for r in client.get("/api/runs").json()["items"])
    assert client.get("/api/worklog").json()["total"] == 8

    stats = client.get("/api/stats").json()  # demo data is left out of the real numbers
    assert stats["runs"] == 0 and stats["work_log_entries"] == 1
    assert stats["demo_runs"] == len(synth.SCENARIOS) and stats["demo_work_log"] == 7
    assert "is_demo" not in str(client.get("/api/worklog/export").json()["entries"])
    assert len(client.get("/api/worklog/export").json()["entries"]) == 1

    assert client.delete("/api/demo").json() == {"runs": len(synth.SCENARIOS), "work_log": 7}
    assert client.get("/api/runs").json()["total"] == 0
    assert [e["id"] for e in client.get("/api/worklog").json()["items"]] == [mine["id"]]
    assert not list(get_settings().runs_dir.glob("*.zip"))


def test_editing_a_demo_entry_makes_it_yours(client):
    client.post("/api/demo")
    demo = client.get("/api/worklog").json()["items"][0]
    assert demo["is_demo"]
    kept = client.put(f"/api/worklog/{demo['id']}", json=entry(title="Now mine")).json()
    assert kept["is_demo"] is False
    client.delete("/api/demo")
    assert [e["title"] for e in client.get("/api/worklog").json()["items"]] == ["Now mine"]


def test_stats_count_runs_findings_and_time(client, upload):
    upload("cpu_overheat")
    upload("failing_disk")
    client.post("/api/worklog", json=entry(category="power", status="fixed", minutes_spent=30))
    client.post("/api/worklog", json=entry(title="Second", category="power", minutes_spent=15))
    stats = client.get("/api/stats?include_demo=true").json()
    assert stats["runs"] == 2 and stats["runs_by_verdict"] == {"warning": 1, "critical": 1}
    assert sum(stats["runs_by_week"].values()) == 2
    assert stats["fault_types_detectable"] >= 29 and stats["fault_types_seen"] == 7
    assert stats["findings_by_code"]["thermal.cpu_hot"] == 1
    assert stats["work_log_by_category"] == {"power": 2} and stats["work_log_minutes"] == 45
    assert stats["work_log_by_status"] == {"fixed": 1, "open": 1}


def test_api_docs_are_served_and_unknown_api_paths_are_404(client):
    assert client.get("/api/docs").status_code == 200
    assert client.get("/api/nope").status_code == 404


def test_built_dashboard_is_served_with_spa_fallback(tmp_path, monkeypatch):
    import warnings

    from fastapi.testclient import TestClient

    from pcdoctor_api import db
    from pcdoctor_api.main import create_app

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>dashboard</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("outside the dashboard folder")
    monkeypatch.setenv("PCDOCTOR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PCDOCTOR_DATABASE_URL", "")
    monkeypatch.setenv("PCDOCTOR_WEB_DIST", str(dist))
    get_settings.cache_clear()
    db.reset_engine()
    with warnings.catch_warnings(), TestClient(create_app()) as client:
        assert "dashboard" in client.get("/").text
        assert "dashboard" in client.get("/runs/abc123").text  # browser-side route
        assert client.get("/assets/app.js").text == "console.log(1)"
        assert client.get("/api/health").json()["status"] == "ok"  # the API still wins
        assert client.get("/api/nope").status_code == 404
        assert "outside" not in client.get("/..%2Fsecret.txt").text
    db.reset_engine()
    get_settings.cache_clear()
