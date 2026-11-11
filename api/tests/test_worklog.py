from __future__ import annotations

from datetime import date

import pytest

from .conftest import entry


def create(client, **fields) -> dict:
    response = client.post("/api/worklog", json=entry(**fields))
    assert response.status_code == 201, response.text
    return response.json()


def test_quick_capture_needs_only_a_title(client):
    body = client.post("/api/worklog", json={"title": "  No POST,  fans spin  "})
    assert body.status_code == 201
    saved = body.json()
    assert saved["title"] == "No POST, fans spin"  # tidied
    assert saved["occurred_on"] == date.today().isoformat()
    assert (saved["status"], saved["category"], saved["device_type"]) == ("open", "other", "other")
    assert saved["components"] == [] and saved["privacy_warnings"] == []


@pytest.mark.parametrize(
    "fields",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"title": "ok", "category": "ghosts"},
        {"title": "ok", "status": "maybe"},
        {"title": "ok", "device_type": "toaster"},
        {"title": "ok", "minutes_spent": -5},
        {"title": "ok", "occurred_on": "not a date"},
        {"title": "ok", "run_id": "does-not-exist"},
    ],
)
def test_invalid_entries_are_rejected(client, fields):
    assert client.post("/api/worklog", json=fields).status_code == 422
    assert client.get("/api/worklog").json()["total"] == 0


def test_codes_and_parts_are_tidied(client):
    saved = create(
        client,
        error_codes=["0x00000124", "0x124", " whea-18 ", "", "Kernel-Power-41"],
        components=[" RTX 3070 ", "rtx 3070", "B550   Tomahawk"],
    )
    assert saved["error_codes"] == ["0x124", "whea-18", "Kernel-Power-41"]
    assert saved["components"] == ["RTX 3070", "B550 Tomahawk"]


def test_update_replaces_the_entry_and_bumps_updated_at(client):
    saved = create(client, status="open")
    changed = client.put(
        f"/api/worklog/{saved['id']}",
        json=entry(status="fixed", root_cause="PSU too small", fix="850 W unit", minutes_spent=45),
    ).json()
    assert changed["status"] == "fixed" and changed["fix"] == "850 W unit"
    assert (
        changed["updated_at"] >= saved["updated_at"]
        and changed["created_at"] == saved["created_at"]
    )
    assert client.get(f"/api/worklog/{saved['id']}").json()["minutes_spent"] == 45


def test_delete_and_404s(client):
    saved = create(client)
    assert client.delete(f"/api/worklog/{saved['id']}").status_code == 204
    assert client.get(f"/api/worklog/{saved['id']}").status_code == 404
    assert client.put("/api/worklog/999", json=entry()).status_code == 404
    assert client.delete("/api/worklog/999").status_code == 404


def test_list_newest_first_with_filters(client):
    create(
        client,
        title="Old thermal job",
        occurred_on="2026-01-05",
        category="thermal",
        status="fixed",
    )
    create(
        client,
        title="New PSU job",
        occurred_on="2026-10-20",
        category="power",
        device_type="laptop",
    )
    create(client, title="Same day, logged later", occurred_on="2026-10-20", category="power")
    titles = [e["title"] for e in client.get("/api/worklog").json()["items"]]
    assert titles == ["Same day, logged later", "New PSU job", "Old thermal job"]
    assert client.get("/api/worklog?category=power").json()["total"] == 2
    assert client.get("/api/worklog?status=fixed").json()["total"] == 1
    assert client.get("/api/worklog?device_type=laptop").json()["total"] == 1
    page = client.get("/api/worklog?limit=1&offset=1").json()
    assert page["total"] == 3 and [e["title"] for e in page["items"]] == ["New PSU job"]


def test_search_needs_every_word_and_looks_in_every_field(client):
    create(
        client,
        title="Loud fans",
        symptoms="Laptop overheats",
        fix="Cleaned dust from heatsink",
        components=["Ryzen 7 5800H"],
        error_codes=["0x124"],
        reference="JOB-0042",
    )
    create(client, title="Dead SSD", symptoms="Not detected in BIOS", category="storage")

    def total(query: str) -> int:
        return client.get("/api/worklog", params={"q": query}).json()["total"]

    assert total("fans") == 1 and total("fan dust") == 1  # stems: "fan" finds "fans"
    assert total("fans SSD") == 0  # both words must be in the same entry
    assert total("5800h") == 1 and total("job-0042") == 1 and total("0x124") == 1
    assert total("storage") == 1  # the category's name counts too
    assert total("") == 2 and total("unicorn") == 0
    assert client.get("/api/worklog?code=0x00000124").json()["total"] == 1


def test_similar_ranks_a_shared_stop_code_first_and_says_why(client):
    create(
        client,
        title="WHEA blue screens",
        category="cpu",
        error_codes=["0x124"],
        status="fixed",
        root_cause="Unstable undervolt",
        fix="Reset BIOS",
    )
    create(
        client, title="Stutter in games", category="memory", symptoms="Hitching every few seconds"
    )
    create(client, title="Printer offline", category="peripheral", symptoms="Wi-Fi printer drops")

    matches = client.post(
        "/api/worklog/similar", json={"text": "blue screen 0x00000124 again"}
    ).json()
    assert matches[0]["entry"]["title"] == "WHEA blue screens"
    assert "Same stop code 0x124 (WHEA_UNCORRECTABLE_ERROR)" in matches[0]["reasons"]
    assert all(m["entry"]["title"] != "Printer offline" for m in matches)

    by_words = client.post("/api/worklog/similar", json={"text": "game keeps lagging"}).json()
    assert by_words[0]["entry"]["title"] == "Stutter in games"  # lagging ~ stutter/hitching
    assert "lagging" in by_words[0]["reasons"][0]

    by_kind = client.post("/api/worklog/similar", json={"category": "cpu"}).json()
    assert [m["entry"]["title"] for m in by_kind] == ["WHEA blue screens"]
    assert (
        client.post("/api/worklog/similar", json={"text": "unrelated nonsense words"}).json() == []
    )


def test_similar_can_exclude_the_entry_being_edited(client):
    first = create(client, title="GPU artifacts", error_codes=["0x116"])
    create(client, title="GPU driver crash", error_codes=["0x116"])
    matches = client.post(
        "/api/worklog/similar", json={"codes": ["0x116"], "exclude_id": first["id"]}
    ).json()
    assert [m["entry"]["title"] for m in matches] == ["GPU driver crash"]


def test_similar_prefers_solved_cases_between_equal_scores(client):
    create(client, title="Open one", error_codes=["0x1A"], status="open", occurred_on="2026-10-01")
    create(
        client, title="Solved one", error_codes=["0x1A"], status="fixed", occurred_on="2026-01-01"
    )
    matches = client.post("/api/worklog/similar", json={"codes": ["0x1a"]}).json()
    assert [m["entry"]["title"] for m in matches] == ["Solved one", "Open one"]


def test_run_page_suggests_earlier_cases_and_lists_entries_logged_from_it(client, upload):
    create(client, title="Earlier 0x124 job", category="cpu", error_codes=["0x124"], status="fixed")
    run_id = upload("whea_bluescreens")["run"]["id"]
    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["similar_cases"][0]["entry"]["title"] == "Earlier 0x124 job"
    assert detail["work_log"] == []

    logged = create(client, title="This job", error_codes=["0x124"], run_id=run_id)
    assert logged["run_id"] == run_id and logged["run_label"]
    detail = client.get(f"/api/runs/{run_id}").json()
    assert [e["title"] for e in detail["work_log"]] == ["This job"]
    # An entry logged from this run is not offered back as a "similar earlier case".
    assert [c["entry"]["title"] for c in detail["similar_cases"]] == ["Earlier 0x124 job"]


def test_deleting_a_run_keeps_the_work_log_entry(client, upload):
    run_id = upload("healthy")["run"]["id"]
    saved = create(client, run_id=run_id)
    assert client.delete(f"/api/runs/{run_id}").status_code == 204
    kept = client.get(f"/api/worklog/{saved['id']}").json()
    assert kept["run_id"] is None and kept["title"] == saved["title"]


def test_healthy_run_offers_no_similar_cases(client, upload):
    create(client, category="thermal")
    assert client.get(f"/api/runs/{upload('healthy')['run']['id']}").json()["similar_cases"] == []


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Call back on 408-555-0142 when done", "phone number"),
        ("Invoice to someone@example.com", "email address"),
        ("Board S/N: MB1234567890", "serial number"),
        ("Mr. Smith dropped it off", "customer"),
        ("RTX 3070, driver 32.0.15.7283, 4101 events, 850 W PSU", None),
        ("Error 0x00000124 at 2026-10-30 12:00, part F4-3600C16-16GVKC", None),
    ],
)
def test_privacy_warnings(client, text, expected):
    warnings = create(client, symptoms=text)["privacy_warnings"]
    if expected is None:
        assert warnings == []
    else:
        assert len(warnings) == 1 and expected in warnings[0]


def test_export_import_round_trip(client):
    create(
        client,
        title="Job A",
        occurred_on="2026-03-01",
        category="gpu",
        status="fixed",
        components=["RTX 3070"],
        error_codes=["0x116"],
        fix="Reseated",
        minutes_spent=30,
    )
    create(client, title="=cmd|' /C calc'!A0", symptoms="spreadsheet injection attempt")
    exported = client.get("/api/worklog/export").json()
    assert exported["format"] == "pcdoctor-worklog" and len(exported["entries"]) == 2

    csv = client.get("/api/worklog/export?format=csv")
    assert "attachment" in csv.headers["content-disposition"]
    assert ",'=cmd|" in csv.text and "RTX 3070" in csv.text  # formula made harmless
    markdown = client.get("/api/worklog/export?format=md").text
    assert "## 2026-03-01 - Job A" in markdown and "**Fix**" in markdown
    assert client.get("/api/worklog/export?format=xml").status_code == 422

    for item in client.get("/api/worklog").json()["items"]:
        client.delete(f"/api/worklog/{item['id']}")
    assert client.post("/api/worklog/import", json=exported).json() == {"imported": 2, "skipped": 0}
    assert client.post("/api/worklog/import", json=exported).json() == {"imported": 0, "skipped": 2}
    restored = client.get("/api/worklog?q=job").json()["items"][0]
    assert restored["components"] == ["RTX 3070"] and restored["minutes_spent"] == 30


def test_import_rejects_bad_files_without_saving_anything(client):
    assert client.post("/api/worklog/import", json={"hello": "world"}).status_code == 400
    bad = {"format": "pcdoctor-worklog", "entries": [{"title": "Good"}, {"title": ""}]}
    response = client.post("/api/worklog/import", json=bad)
    assert response.status_code == 400 and "Entry 2" in response.json()["detail"]
    assert client.get("/api/worklog").json()["total"] == 0
