"""Revoking one private link (threat model #11): the master can cut off a
single share key or photo link without deleting the run or the photos."""

from __future__ import annotations

from .test_auth import run_zip
from .test_oauth import member, provider  # noqa: F401 - fixtures


def guest_upload(browser, label: str = "") -> dict:
    sent = browser.post("/api/runs", files=run_zip(), data={"label": label})
    assert sent.status_code in (200, 201), sent.text
    return sent.json()


def test_revoking_one_key_leaves_the_other_working(client, guest):
    first = guest_upload(guest, "first person")
    second = guest_upload(guest, "second person")
    run_id = first["run"]["id"]
    assert second["run"]["id"] == run_id and first["share_key"] != second["share_key"]

    links = client.get(f"/api/runs/{run_id}/links")
    assert links.status_code == 200
    listed = links.json()
    assert [link["label"] for link in listed] == ["first person", "second person"]
    assert all(set(link) == {"id", "label", "created_at", "member"} for link in listed)
    assert not any(link["member"] for link in listed)
    text = links.text
    assert first["share_key"] not in text and second["share_key"] not in text

    assert client.delete(f"/api/runs/{run_id}/links/{listed[0]['id']}").status_code == 204
    assert guest.get(f"/api/shared/{first['share_key']}").status_code == 404
    assert guest.get(f"/api/shared/{first['share_key']}/series").status_code == 404
    still = guest.get(f"/api/shared/{second['share_key']}")
    assert still.status_code == 200 and still.json()["label"] == "second person"
    assert client.get(f"/api/runs/{run_id}").status_code == 200  # the run stays
    assert [link["id"] for link in client.get(f"/api/runs/{run_id}/links").json()] == [
        listed[1]["id"]
    ]
    # Revoking it again, or one that never existed, is a plain 404.
    assert client.delete(f"/api/runs/{run_id}/links/{listed[0]['id']}").status_code == 404
    assert client.delete(f"/api/runs/{run_id}/links/999999").status_code == 404


def test_a_link_cannot_be_revoked_through_another_run(client, guest):
    one = guest_upload(guest)
    other = guest.post("/api/runs", files=run_zip("failing_disk")).json()
    link_id = client.get(f"/api/runs/{one['run']['id']}/links").json()[0]["id"]
    assert client.delete(f"/api/runs/{other['run']['id']}/links/{link_id}").status_code == 404
    assert guest.get(f"/api/shared/{one['share_key']}").status_code == 200
    assert client.get("/api/runs/no-such-run/links").status_code == 404


def test_a_guest_cannot_list_or_revoke_links(client, guest):
    sent = guest_upload(guest)
    run_id = sent["run"]["id"]
    link_id = client.get(f"/api/runs/{run_id}/links").json()[0]["id"]
    assert guest.get(f"/api/runs/{run_id}/links").status_code == 401
    assert guest.delete(f"/api/runs/{run_id}/links/{link_id}").status_code == 401
    assert guest.get(f"/api/shared/{sent['share_key']}").status_code == 200

    client.post("/api/photo-links", json={"label": "bench 2"})
    photo_link = client.get("/api/photo-links").json()[0]["id"]
    assert guest.get("/api/photo-links").status_code == 401
    assert guest.delete(f"/api/photo-links/{photo_link}").status_code == 401
    assert len(client.get("/api/photo-links").json()) == 1


def test_a_member_cannot_list_or_revoke_and_is_marked_as_a_member(client, member):  # noqa: F811
    sent = member.post("/api/runs", files=run_zip()).json()
    run_id = sent["run"]["id"]
    listed = client.get(f"/api/runs/{run_id}/links").json()
    assert [link["member"] for link in listed] == [True]
    assert member.get(f"/api/runs/{run_id}/links").status_code == 403
    assert member.delete(f"/api/runs/{run_id}/links/{listed[0]['id']}").status_code == 403
    assert member.get("/api/photo-links").status_code == 403
    assert member.get(f"/api/shared/{sent['share_key']}").status_code == 200


def test_a_revoked_photo_link_refuses_new_photos(client, guest):
    from datetime import timedelta

    from sqlalchemy import update

    from pcdoctor_api import db
    from pcdoctor_api.db import utcnow
    from pcdoctor_api.models import PhotoLink

    kept = client.post("/api/photo-links", json={"label": "bench 1"}).json()
    revoked = client.post("/api/photo-links", json={"label": "bench 2"}).json()
    expired = client.post("/api/photo-links", json={"label": "old"}).json()
    with db.get_engine().begin() as connection:
        connection.execute(
            update(PhotoLink)
            .where(PhotoLink.label == "old")
            .values(expires_at=utcnow() - timedelta(minutes=1))
        )
    assert guest.get(f"/api/photo-links/{expired['token']}").status_code == 404

    listing = client.get("/api/photo-links")
    assert listing.status_code == 200
    links = listing.json()
    assert [link["label"] for link in links] == ["bench 2", "bench 1"]  # open ones, newest first
    assert all(set(link) == {"id", "label", "created_at", "expires_at"} for link in links)
    assert kept["token"] not in listing.text and revoked["token"] not in listing.text

    target = next(link for link in links if link["label"] == "bench 2")
    assert client.delete(f"/api/photo-links/{target['id']}").status_code == 204
    assert guest.get(f"/api/photo-links/{revoked['token']}").status_code == 404
    refused = guest.post(
        f"/api/photo-links/{revoked['token']}/photos",
        # The link is checked before the file is even looked at.
        files={"file": ("p.png", b"not looked at", "image/png")},
    )
    assert refused.status_code == 404
    assert client.get("/api/inbox").json()["items"] == []
    assert guest.get(f"/api/photo-links/{kept['token']}").status_code == 200
    assert [link["label"] for link in client.get("/api/photo-links").json()] == ["bench 1"]
    assert client.delete(f"/api/photo-links/{target['id']}").status_code == 404
