"""Who can see what. The rule: a guest can send things in and see their own
one run through its private link - and nothing else, ever."""

from __future__ import annotations

import io

import pytest
from pcdoctor_analysis import synth

from pcdoctor_api.config import get_settings
from pcdoctor_api.services import ai, auth, photo

from .conftest import MASTER, entry

needs_ocr = pytest.mark.skipif(not photo.available(), reason="Tesseract is not installed")


def run_zip(name: str = "whea_bluescreens") -> dict:
    return {"file": (f"{name}.zip", synth.build(name).zip_bytes(), "application/zip")}


def picture(text: str = "Stop code: CRITICAL_PROCESS_DIED") -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1280, 720), (0, 120, 215))
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 30)
    except OSError:
        font = ImageFont.load_default(size=30)
    draw = ImageDraw.Draw(image)
    draw.text(
        (90, 200), "Your PC ran into a problem and needs to restart.", fill="white", font=font
    )
    draw.text((90, 300), text, fill="white", font=font)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


# ------------------------------------------------------------------ sign-in


def test_status_setup_and_sign_in_cycle(client, guest):
    assert client.get("/api/auth/status").json() == {
        "setup_needed": False,
        "signed_in": True,
        "username": "huey",
        "role": "master",
    }
    assert guest.get("/api/auth/status").json()["signed_in"] is False

    assert (
        guest.post("/api/auth/login", json={**MASTER, "password": "wrong password!"}).status_code
        == 401
    )
    assert (
        guest.post("/api/auth/login", json={"username": "nobody", "password": "x"}).status_code
        == 401
    )
    signed = guest.post("/api/auth/login", json=MASTER)
    assert signed.status_code == 200
    cookie = signed.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert guest.get("/api/runs").status_code == 200

    assert guest.post("/api/auth/logout").json() == {"signed_in": False}
    assert guest.get("/api/runs").status_code == 401


def test_the_master_account_can_only_be_created_once_and_needs_the_setup_code(client, guest):
    again = guest.post(
        "/api/auth/setup",
        json={"username": "evil", "password": "long enough pw", "setup_code": "x"},
    )
    assert again.status_code == 409


def test_setup_rules(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from pcdoctor_api import db
    from pcdoctor_api.main import create_app

    monkeypatch.setenv("PCDOCTOR_DATA_DIR", str(tmp_path / "fresh"))
    monkeypatch.setenv("PCDOCTOR_DATABASE_URL", "")
    get_settings.cache_clear()
    db.reset_engine()
    with TestClient(create_app()) as fresh:
        assert fresh.get("/api/auth/status").json()["setup_needed"] is True
        assert fresh.get("/api/runs").status_code == 401  # nothing is open before setup either
        code = auth.setup_code(get_settings().data_dir)
        body = {"username": "huey", "password": "correct horse battery", "setup_code": "00000000"}
        assert fresh.post("/api/auth/setup", json=body).status_code == 403  # wrong code
        assert (
            fresh.post(
                "/api/auth/setup", json={**body, "setup_code": code, "password": "short"}
            ).status_code
            == 422
        )
        assert fresh.post("/api/auth/setup", json={**body, "setup_code": code}).status_code == 200
        assert not (get_settings().data_dir / "setup-code.txt").exists()  # used up
        assert fresh.get("/api/runs").status_code == 200
    db.reset_engine()
    get_settings.cache_clear()


def test_passwords_are_hashed_and_sessions_are_stored_as_hashes(client):
    from sqlalchemy import text

    from pcdoctor_api import db

    with db.get_engine().connect() as connection:
        stored = connection.execute(text("select password_hash from accounts")).scalar_one()
        session = connection.execute(text("select token_hash from sessions")).scalar_one()
    assert stored.startswith("scrypt$") and MASTER["password"] not in stored
    assert session != client.cookies.get(auth.COOKIE) and len(session) == 64
    assert auth.verify_password(MASTER["password"], stored)
    assert not auth.verify_password("something else", stored)
    assert not auth.verify_password("x", "garbage")


def test_too_many_wrong_passwords_are_slowed_down(client, guest):
    for _ in range(8):
        assert (
            guest.post("/api/auth/login", json={**MASTER, "password": "nope nope nope"}).status_code
            == 401
        )
    assert guest.post("/api/auth/login", json=MASTER).status_code == 429


def test_an_expired_or_made_up_session_is_not_signed_in(client, guest):
    guest.cookies.set(auth.COOKIE, "made-up-token")
    assert guest.get("/api/worklog").status_code == 401


# ------------------------------------------------------- what a guest can do

MASTER_ONLY = [
    ("get", "/api/runs"),
    ("get", "/api/runs/abc"),
    ("get", "/api/runs/abc/series"),
    ("get", "/api/runs/abc/download"),
    ("get", "/api/runs/abc/compare"),
    ("delete", "/api/runs/abc"),
    ("post", "/api/runs/abc/reanalyze"),
    ("patch", "/api/runs/abc"),
    ("get", "/api/worklog"),
    ("post", "/api/worklog"),
    ("get", "/api/worklog/1"),
    ("put", "/api/worklog/1"),
    ("delete", "/api/worklog/1"),
    ("post", "/api/worklog/similar"),
    ("get", "/api/worklog/export"),
    ("post", "/api/worklog/import"),
    ("get", "/api/stats"),
    ("post", "/api/demo"),
    ("delete", "/api/demo"),
    ("post", "/api/photos"),
    ("post", "/api/photo-links"),
    ("get", "/api/inbox"),
    ("get", "/api/inbox/abc/image"),
    ("post", "/api/inbox/abc/describe"),
    ("patch", "/api/inbox/abc"),
    ("delete", "/api/inbox/abc"),
    ("get", "/api/assist"),
    ("post", "/api/assist/draft"),
    ("post", "/api/assist/troubleshoot"),
    ("get", "/api/accounts"),
    ("delete", "/api/accounts/1"),
    ("post", "/api/live"),
    ("get", "/api/live"),
    ("get", "/api/live/abc"),
    ("delete", "/api/live/abc"),
]
# Any signed-in account may use these, but each sees only what is its own.
SIGNED_IN = [
    ("get", "/api/me/runs"),
    ("get", "/api/me/runs/abc"),
    ("get", "/api/me/runs/abc/series"),
    ("delete", "/api/me/runs/abc"),
    ("get", "/api/auth/identities"),
    ("delete", "/api/auth/identities/1"),
]


@pytest.mark.parametrize("method, path", MASTER_ONLY + SIGNED_IN)
def test_everything_stored_needs_a_sign_in(guest, method, path):
    response = getattr(guest, method)(path)
    assert response.status_code == 401, f"{method.upper()} {path} answered {response.status_code}"


def test_every_api_route_is_either_master_only_or_deliberately_public(client):
    """A new endpoint must be added to one list or the other - never open by accident."""
    public = {
        ("GET", "/api/health"),
        ("GET", "/api/meta"),
        ("GET", "/api/stopcodes"),
        ("GET", "/api/stopcodes/{code}"),
        ("GET", "/api/noboot"),
        ("GET", "/api/collector"),
        ("GET", "/api/collector.zip"),
        ("GET", "/api/collector/presentmon.zip"),  # only the pinned file
        ("POST", "/api/runs"),
        ("GET", "/api/shared/{key}"),
        ("GET", "/api/shared/{key}/series"),
        ("GET", "/api/auth/status"),
        ("POST", "/api/auth/setup"),
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/logout"),
        ("GET", "/api/photo-links/{token}"),
        ("POST", "/api/photo-links/{token}/photos"),
        ("GET", "/api/metrics"),  # token only; see test_scale.py
        ("GET", "/api/auth/oauth"),
        ("GET", "/api/auth/oauth/{name}/start"),
        ("GET", "/api/auth/oauth/{name}/callback"),
        ("POST", "/api/live/{token}/samples"),  # token: can add samples, reads nothing
    }
    import re

    listed = {(m.upper(), re.sub(r"abc|1$", "{x}", p)) for m, p in MASTER_ONLY + SIGNED_IN}
    for route in client.app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/") or path in ("/api/docs", "/api/openapi.json"):
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            generic = re.sub(r"\{[a-z_]+\}", "{x}", path)
            assert (method, path) in public or (method, generic) in listed, (
                f"unclassified: {method} {path}"
            )


def test_a_guest_gets_a_private_link_to_their_own_run_and_nothing_else(client, guest):
    client.post(
        "/api/worklog", json=entry(title="Master's earlier 0x124 job", error_codes=["0x124"])
    )
    mine = client.post("/api/runs", files=run_zip("failing_disk")).json()
    assert mine["share_key"] is None  # the master does not need one

    sent = guest.post("/api/runs", files=run_zip())
    assert sent.status_code == 201
    key, run_id = sent.json()["share_key"], sent.json()["run"]["id"]
    assert len(key) >= 40 and sent.json()["run"]["source"] == "guest"

    seen = guest.get(f"/api/shared/{key}")
    assert seen.status_code == 200
    body = seen.json()
    assert "fatal hardware" in body["headline"] and len(body["findings"]) == 2
    # The master's work log matches this run - the guest must not get it.
    assert body["similar_cases"] == [] and body["work_log"] == [] and body["notes"] == ""
    assert client.get(f"/api/runs/{run_id}").json()["similar_cases"] != []
    assert guest.get(f"/api/shared/{key}/series").status_code == 200

    assert guest.get(f"/api/runs/{run_id}").status_code == 401  # not by id
    assert guest.get(f"/api/shared/{run_id}").status_code == 404  # the id is not the key
    assert guest.get(f"/api/shared/{mine['run']['id']}").status_code == 404
    assert guest.get("/api/shared/" + "A" * 43).status_code == 404
    assert guest.get("/api/stopcodes/0x124").json()["cases"] == []  # public meaning, private cases
    assert client.get("/api/stopcodes/0x124").json()["cases"] != []
    assert {r["source"] for r in client.get("/api/runs").json()["items"]} == {"guest", "master"}


def test_the_share_key_is_not_stored(client, guest):
    from sqlalchemy import text

    from pcdoctor_api import db

    key = guest.post("/api/runs", files=run_zip()).json()["share_key"]
    with db.get_engine().connect() as connection:
        stored = connection.execute(text("select key_hash from share_keys")).scalar_one()
    assert stored == auth.token_hash(key) and key not in stored


def test_a_second_upload_of_the_same_file_does_not_break_the_first_link(client, guest):
    client.post("/api/runs", files=run_zip("bad_ram"), data={"label": "master's own note"})
    first = guest.post("/api/runs", files=run_zip("bad_ram"), data={"label": "first"}).json()
    second = guest.post("/api/runs", files=run_zip("bad_ram"), data={"label": "second"}).json()
    assert second["duplicate"] and second["run"]["id"] == first["run"]["id"]
    assert first["share_key"] != second["share_key"]
    # Each guest keeps a working link and sees only the label they typed.
    assert first["run"]["label"] == "first" and second["run"]["label"] == "second"
    assert guest.get(f"/api/shared/{first['share_key']}").json()["label"] == "first"
    assert guest.get(f"/api/shared/{second['share_key']}").json()["label"] == "second"
    # The master's own label stays on the run.
    assert client.get(f"/api/runs/{first['run']['id']}").json()["label"] == "master's own note"


def test_deleting_a_run_removes_its_links(client, guest):
    shared = guest.post("/api/runs", files=run_zip("bad_ram")).json()
    assert client.delete(f"/api/runs/{shared['run']['id']}").status_code == 204
    assert guest.get(f"/api/shared/{shared['share_key']}").status_code == 404


def test_guest_uploads_are_rate_limited(client, guest, monkeypatch):
    monkeypatch.setattr(auth.guest_uploads, "limit", 2)
    assert guest.post("/api/runs", files=run_zip("healthy")).status_code == 201
    assert guest.post("/api/runs", files=run_zip("bad_ram")).status_code == 201
    assert guest.post("/api/runs", files=run_zip("power_loss")).status_code == 429
    assert (
        client.post("/api/runs", files=run_zip("power_loss")).status_code == 201
    )  # the master is not limited


def test_setup_guesses_are_rate_limited_and_the_code_is_long(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from pcdoctor_api import db
    from pcdoctor_api.main import create_app

    monkeypatch.setenv("PCDOCTOR_DATA_DIR", str(tmp_path / "fresh"))
    monkeypatch.setenv("PCDOCTOR_DATABASE_URL", "")
    get_settings.cache_clear()
    db.reset_engine()
    auth.login_attempts.reset()
    try:
        with TestClient(create_app()) as fresh:
            code = auth.setup_code(get_settings().data_dir)
            assert len(code) == 16
            body = {"username": "x", "password": "long enough pw", "setup_code": "0" * 16}
            answers = [fresh.post("/api/auth/setup", json=body).status_code for _ in range(9)]
            assert answers[:8] == [403] * 8 and answers[8] == 429
            # Even the right code waits now: guessing is what the limit stops.
            right = {**body, "setup_code": code}
            assert fresh.post("/api/auth/setup", json=right).status_code == 429
    finally:
        auth.login_attempts.reset()
        db.reset_engine()
        get_settings.cache_clear()


def test_the_database_allows_only_one_master(client, session):
    from sqlalchemy.exc import IntegrityError

    from pcdoctor_api.models import Account

    session.add(Account(username="second", password_hash="x", role="master"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.add(Account(username="member-1", password_hash="x", role="member"))
    session.add(Account(username="member-2", password_hash="x", role="member"))
    session.commit()  # members are not limited


def test_the_bot_token_only_raises_the_upload_limit(client, guest, monkeypatch):
    from pcdoctor_api.config import get_settings

    monkeypatch.setattr(get_settings(), "bot_token", "a-long-bot-token")
    monkeypatch.setattr(auth.guest_uploads, "limit", 1)
    monkeypatch.setattr(auth.bot_uploads, "limit", 3)
    bot = {auth.BOT_TOKEN_HEADER: "a-long-bot-token"}
    assert guest.post("/api/runs", files=run_zip("healthy")).status_code == 201
    assert guest.post("/api/runs", files=run_zip("bad_ram")).status_code == 429
    # Same address, but with the bot token: its own, higher limit.
    uploaded = guest.post("/api/runs", files=run_zip("bad_ram"), headers=bot)
    assert uploaded.status_code == 201 and uploaded.json()["share_key"]
    assert uploaded.json()["run"]["source"] == "guest"  # still a guest upload
    assert guest.post("/api/runs", files=run_zip("power_loss"), headers=bot).status_code == 201
    assert guest.post("/api/runs", files=run_zip("healthy"), headers=bot).status_code in (200, 201)
    assert guest.post("/api/runs", files=run_zip("healthy"), headers=bot).status_code == 429
    # A wrong token is refused, not quietly treated as a guest.
    wrong = {auth.BOT_TOKEN_HEADER: "a-long-bot-tokem"}
    assert guest.post("/api/runs", files=run_zip("healthy"), headers=wrong).status_code == 401
    # The token reads nothing.
    for path in ("/api/runs", "/api/worklog"):
        assert guest.get(path, headers=bot).status_code == 401


def test_a_bot_token_is_refused_when_none_is_configured(client, guest):
    bot = {auth.BOT_TOKEN_HEADER: ""}
    assert guest.post("/api/runs", files=run_zip(), headers=bot).status_code == 401
    bot = {auth.BOT_TOKEN_HEADER: "anything"}
    assert guest.post("/api/runs", files=run_zip(), headers=bot).status_code == 401


# ------------------------------------------------------------ photo inbox


def test_qr_link_lets_a_phone_send_a_photo_but_read_nothing(client, guest):
    link = client.post("/api/photo-links", json={"label": "  bench 2  "}).json()
    assert link["path"] == f"/snap/{link['token']}" and link["label"] == "bench 2"
    assert guest.get(f"/api/photo-links/{link['token']}").json()["label"] == "bench 2"

    sent = guest.post(
        f"/api/photo-links/{link['token']}/photos",
        files={"file": ("p.png", picture(), "image/png")},
    )
    assert sent.status_code == 201 and sent.json() == {"received": True}  # nothing else leaks back

    inbox = client.get("/api/inbox").json()
    assert inbox["waiting"] == 1 and inbox["items"][0]["label"] == "bench 2"
    photo_id = inbox["items"][0]["id"]
    image = client.get(f"/api/inbox/{photo_id}/image")
    assert image.status_code == 200 and image.content[:3] == b"\xff\xd8\xff"  # stored as JPEG
    assert guest.get(f"/api/inbox/{photo_id}/image").status_code == 401

    assert (
        guest.post(
            "/api/photo-links/not-a-token/photos", files={"file": ("p.png", picture(), "image/png")}
        ).status_code
        == 404
    )
    bad = guest.post(
        f"/api/photo-links/{link['token']}/photos", files={"file": ("p.png", b"nope", "image/png")}
    )
    assert bad.status_code == 400

    saved = client.post("/api/worklog", json=entry(title="From photo")).json()
    assert (
        client.patch(f"/api/inbox/{photo_id}", json={"work_log_id": saved["id"]}).json()[
            "work_log_id"
        ]
        == saved["id"]
    )
    assert client.get("/api/inbox").json()["waiting"] == 0
    assert client.patch(f"/api/inbox/{photo_id}", json={"work_log_id": 999}).status_code == 422
    assert client.delete(f"/api/inbox/{photo_id}").status_code == 204
    assert not list(get_settings().photos_dir.glob("*.jpg"))


@needs_ocr
def test_inbox_photo_is_read_and_matched_to_earlier_jobs(client, guest):
    client.post("/api/worklog", json=entry(title="Dead SSD", error_codes=["0xEF"], status="fixed"))
    token = client.post("/api/photo-links", json={}).json()["token"]
    guest.post(
        f"/api/photo-links/{token}/photos", files={"file": ("p.png", picture(), "image/png")}
    )
    item = client.get("/api/inbox").json()["items"][0]
    assert [code["hex"] for code in item["stop_codes"]] == ["0xEF"] and item["is_blue_screen"]
    assert [case["entry"]["title"] for case in item["cases"]] == ["Dead SSD"]


def test_stored_photos_have_their_location_data_removed(client, guest):
    from PIL import Image

    source = Image.new("RGB", (64, 64), "white")
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # camera make
    exif[0x8825] = {1: "N", 2: (37.0, 20.0, 0.0)}  # GPS
    raw = io.BytesIO()
    source.save(raw, "JPEG", exif=exif)
    assert b"PhoneMaker" in raw.getvalue()

    token = client.post("/api/photo-links", json={}).json()["token"]
    guest.post(
        f"/api/photo-links/{token}/photos", files={"file": ("p.jpg", raw.getvalue(), "image/jpeg")}
    )
    stored = next(get_settings().photos_dir.glob("*.jpg")).read_bytes()
    assert b"PhoneMaker" not in stored and len(Image.open(io.BytesIO(stored)).getexif()) == 0


def test_expired_photo_link_stops_working(client, guest):
    from datetime import timedelta

    from sqlalchemy import update

    from pcdoctor_api import db
    from pcdoctor_api.db import utcnow
    from pcdoctor_api.models import PhotoLink

    token = client.post("/api/photo-links", json={}).json()["token"]
    with db.get_engine().begin() as connection:
        connection.execute(update(PhotoLink).values(expires_at=utcnow() - timedelta(minutes=1)))
    assert guest.get(f"/api/photo-links/{token}").status_code == 404
    assert (
        guest.post(
            f"/api/photo-links/{token}/photos", files={"file": ("p.png", picture(), "image/png")}
        ).status_code
        == 404
    )


# -------------------------------------------------------------- AI helper


class FakeAnthropic:
    """Stands in for the real client: records what was sent, returns a canned reply."""

    sent: list[dict] = []
    reply = '```json\n{"title": "Blue screen: CRITICAL_PROCESS_DIED", "category": "storage", "symptoms": "Blue screen at boot.", "steps": "", "root_cause": "", "fix": "", "error_codes": ["0xEF"], "components": [], "password": "should be dropped"}\n```'

    def __init__(self, **_):
        self.messages = self

    def create(self, **kwargs):
        FakeAnthropic.sent.append(kwargs)
        return type(
            "Reply", (), {"content": [type("Block", (), {"text": FakeAnthropic.reply})()]}
        )()


def test_ai_helper_is_off_without_a_key_and_says_so(client):
    assert client.get("/api/assist").json()["available"] is False
    response = client.post("/api/assist/draft", json={"notes": "swapped the PSU"})
    assert response.status_code == 503 and "ANTHROPIC_API_KEY" in response.json()["detail"]
    assert client.post("/api/assist/draft", json={}).status_code == 422


def test_ai_draft_sends_only_the_material_and_cleans_the_answer(client, monkeypatch):
    import sys
    import types

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    get_settings.cache_clear()
    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=FakeAnthropic))
    FakeAnthropic.sent.clear()
    run_id = client.post("/api/runs", files=run_zip()).json()["run"]["id"]

    draft = client.post(
        "/api/assist/draft", json={"run_id": run_id, "notes": "reset BIOS, stable since"}
    )
    assert draft.status_code == 200, draft.text
    body = draft.json()
    assert body["title"].startswith("Blue screen") and body["category"] == "storage"
    assert body["error_codes"] == ["0xEF"] and "password" not in body  # unknown fields dropped
    request = FakeAnthropic.sent[0]
    material = request["messages"][0]["content"]
    assert "WHEA_UNCORRECTABLE_ERROR" in material and "reset BIOS, stable since" in material
    assert "Never invent" in request["system"] and "test-key" not in material

    FakeAnthropic.reply = "I cannot help with that."
    assert client.post("/api/assist/draft", json={"notes": "x"}).status_code == 502
    assert client.post("/api/assist/draft", json={"run_id": "missing"}).status_code == 404


def test_ai_answer_cleaning():
    assert ai.clean_draft({"title": " a\n b ", "category": "ghosts", "error_codes": "0x1"}) == {
        "title": "a b",
        "category": "other",
        "symptoms": "",
        "steps": "",
        "root_cause": "",
        "fix": "",
        "error_codes": [],
        "components": [],
    }
    notes = ai.clean_photo_notes(
        {"summary": "DRAM LED lit", "observations": ["DRAM LED on", ""], "category": "memory"}
    )
    assert notes["observations"] == ["DRAM LED on"] and notes["category"] == "memory"
    with pytest.raises(ai.AiError):
        ai.parse_json("[1, 2]")


def test_troubleshooter_may_only_cite_findings_the_run_has(client, monkeypatch):
    import json
    import sys
    import types

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    get_settings.cache_clear()
    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=FakeAnthropic))
    FakeAnthropic.sent.clear()
    run_id = client.post("/api/runs", files=run_zip()).json()["run"]["id"]
    codes = [f["code"] for f in client.get(f"/api/runs/{run_id}").json()["findings"]]
    FakeAnthropic.reply = json.dumps(
        {
            "likely_cause": "The CPU is faulty.",
            "category": "cpu",
            "confidence": "high",
            "because": [
                {"finding": codes[0], "why": "fatal hardware errors"},
                {"finding": "made.up", "why": "invented"},
            ],
            "steps": ["Reset the BIOS to defaults and retest."],
        }
    )
    answer = client.post("/api/assist/troubleshoot", json={"run_id": run_id, "question": "PSU?"})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert [b["finding"] for b in body["because"]] == [codes[0]] and body["confidence"] == "high"
    material = FakeAnthropic.sent[0]["messages"][0]["content"]
    assert f"[{codes[0]}]" in material and "The technician asks: PSU?" in material

    FakeAnthropic.reply = json.dumps({"likely_cause": "x", "confidence": "high", "because": []})
    body = client.post("/api/assist/troubleshoot", json={"run_id": run_id}).json()
    assert body["confidence"] == "low" and body["category"] == "other"
    assert client.post("/api/assist/troubleshoot", json={"run_id": "nope"}).status_code == 404


@pytest.mark.parametrize(
    ("hops", "header", "expected"),
    [
        (1, "203.0.113.9", "203.0.113.9"),  # Compose: nginx added the caller
        (2, "203.0.113.9, 10.42.0.7", "203.0.113.9"),  # k3s: Traefik, then nginx
        (2, "6.6.6.6, 203.0.113.9, 10.42.0.7", "203.0.113.9"),  # a forged entry is ignored
        (1, "6.6.6.6, 203.0.113.9", "203.0.113.9"),
        (2, "203.0.113.9", "203.0.113.9"),  # fewer entries than hops
    ],
)
def test_the_rate_limit_address_skips_only_our_own_proxies(hops, header, expected):
    from types import SimpleNamespace

    from pcdoctor_api.config import Settings
    from pcdoctor_api.deps import client_key

    request = SimpleNamespace(
        headers={"x-forwarded-for": header}, client=SimpleNamespace(host="10.42.0.99")
    )
    settings = Settings(trust_proxy=True, proxy_hops=hops)
    assert client_key(request, settings) == expected
    assert client_key(request, Settings(trust_proxy=False)) == "10.42.0.99"


def test_every_response_carries_the_security_headers(client, guest):
    for response in (guest.get("/api/health"), guest.get("/api/runs"), client.get("/api/runs")):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"  # private links stay private
        assert response.headers["x-frame-options"] == "DENY"
        policy = response.headers["content-security-policy"]
        assert "script-src 'self'" in policy and "frame-ancestors 'none'" in policy
    # The nginx copy of the policy (Docker) must match the API's.
    from pathlib import Path

    from pcdoctor_api.main import CONTENT_SECURITY_POLICY

    snippet = (Path(__file__).resolve().parents[2] / "web" / "security-headers.conf").read_text()
    assert f'Content-Security-Policy "{CONTENT_SECURITY_POLICY}"' in snippet
