"""Phase 4: sign-in with Discord or Google, and member accounts."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from pcdoctor_api.config import get_settings
from pcdoctor_api.models import Account, Identity, Run
from pcdoctor_api.services import notify, oauth

from .test_auth import MASTER_ONLY, run_zip


class FakeProvider:
    """Stands in for Discord: checks what a real provider checks."""

    def __init__(self) -> None:
        self.subject = "person-1"
        self.challenge = ""
        self.token_requests: list[dict] = []
        self.accept = True

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_requests.append(form)
            ok = (
                self.accept
                and form["client_secret"] == "discord-secret"
                and form["code"] == "the-code"
                and oauth.challenge_for(form["code_verifier"]) == self.challenge
            )
            if not ok:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer"})
        assert request.headers["authorization"] == "Bearer tok"
        return httpx.Response(
            200, json={"id": self.subject, "username": "RealName", "email": "x@y.z"}
        )


@pytest.fixture
def provider(client, monkeypatch) -> FakeProvider:
    monkeypatch.setenv("PCDOCTOR_PUBLIC_URL", "https://pcdoctor.test")
    monkeypatch.setenv("PCDOCTOR_DISCORD_CLIENT_ID", "discord-id")
    monkeypatch.setenv("PCDOCTOR_DISCORD_CLIENT_SECRET", "discord-secret")
    get_settings.cache_clear()
    fake = FakeProvider()
    monkeypatch.setattr(
        oauth, "http_client", lambda: httpx.Client(transport=httpx.MockTransport(fake.handler))
    )
    return fake


def browser(client) -> TestClient:
    # https, because the sign-in cookie is marked Secure when the public address is.
    other = TestClient(client.app, base_url="https://testserver", follow_redirects=False)
    other.cookies.clear()
    return other


def sign_in(visitor: TestClient, fake: FakeProvider, intent: str = "login") -> httpx.Response:
    """Walk the whole flow the way a browser would."""
    started = visitor.get(f"/api/auth/oauth/discord/start?intent={intent}", follow_redirects=False)
    assert started.status_code == 303, started.text
    query = parse_qs(urlparse(started.headers["location"]).query)
    fake.challenge = query["code_challenge"][0]
    return visitor.get(
        f"/api/auth/oauth/discord/callback?code=the-code&state={query['state'][0]}",
        follow_redirects=False,
    )


def test_nothing_is_offered_until_it_is_configured(client, guest):
    assert guest.get("/api/auth/oauth").json() == {"providers": [], "signup": False}
    assert guest.get("/api/auth/oauth/discord/start", follow_redirects=False).status_code == 404
    assert guest.get("/api/auth/oauth/myspace/start", follow_redirects=False).status_code == 404


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://pcdoctor.example.com", True),
        ("http://localhost:8080", True),
        ("http://127.0.0.1:8080", True),
        ("http://192.168.1.20:8080", True),
        ("http://pcdoctor.example.com", False),
        ("http://8.8.8.8", False),
        ("ftp://pcdoctor.example.com", False),
        ("pcdoctor.example.com", False),
    ],
)
def test_the_public_address_must_be_https_across_the_internet(url, ok):
    assert oauth.public_url_ok(url) is ok


def test_sign_in_is_off_with_a_plain_http_public_address(client, provider, monkeypatch, guest):
    monkeypatch.setattr(get_settings(), "public_url", "http://pcdoctor.example.com")
    assert guest.get("/api/auth/oauth").json()["providers"] == []
    assert guest.get("/api/auth/oauth/discord/start", follow_redirects=False).status_code == 404


def test_the_request_to_the_provider_asks_for_the_least(client, provider):
    visitor = browser(client)
    started = visitor.get("/api/auth/oauth/discord/start", follow_redirects=False)
    target = urlparse(started.headers["location"])
    query = {k: v[0] for k, v in parse_qs(target.query).items()}
    assert target.netloc == "discord.com" and query["scope"] == "identify"  # no email
    assert query["redirect_uri"] == "https://pcdoctor.test/api/auth/oauth/discord/callback"
    assert query["code_challenge_method"] == "S256" and len(query["state"]) >= 24
    cookie = started.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "Path=/api/auth/oauth" in cookie


def test_a_stranger_cannot_sign_in_unless_sign_up_is_open(client, provider, monkeypatch, session):
    visitor = browser(client)
    refused = sign_in(visitor, provider)
    assert refused.headers["location"] == "https://pcdoctor.test/login?problem=not_linked"
    assert visitor.get("/api/auth/status").json()["signed_in"] is False

    monkeypatch.setenv("PCDOCTOR_OAUTH_SIGNUP", "true")
    get_settings.cache_clear()
    assert sign_in(visitor, provider).headers["location"] == "https://pcdoctor.test/"
    status = visitor.get("/api/auth/status").json()
    assert status["signed_in"] and status["role"] == "member"
    assert status["username"].startswith("discord-") and "RealName" not in status["username"]
    db = session
    identity = db.scalar(select(Identity))
    assert (identity.provider, identity.subject) == ("discord", "person-1")
    assert len(provider.token_requests[-1]["code_verifier"]) >= 43  # PKCE was really used
    # Signing in again finds the same account instead of making another.
    again = browser(client)
    sign_in(again, provider)
    assert again.get("/api/auth/status").json()["username"] == status["username"]
    assert len(list(db.scalars(select(Account)))) == 2


def test_a_forged_or_replayed_callback_is_refused(client, provider, monkeypatch):
    monkeypatch.setenv("PCDOCTOR_OAUTH_SIGNUP", "true")
    get_settings.cache_clear()
    visitor = browser(client)
    # No sign-in was started in this browser: there is no cookie to match.
    forged = visitor.get(
        "/api/auth/oauth/discord/callback?code=the-code&state=guess", follow_redirects=False
    )
    assert forged.headers["location"].endswith("problem=expired")
    # Started, but the state that comes back is not ours.
    visitor.get("/api/auth/oauth/discord/start", follow_redirects=False)
    wrong = visitor.get(
        "/api/auth/oauth/discord/callback?code=the-code&state=other", follow_redirects=False
    )
    assert wrong.headers["location"].endswith("problem=expired")
    # The provider rejects the code.
    provider.accept = False
    assert sign_in(visitor, provider).headers["location"].endswith("problem=provider")
    assert visitor.get("/api/auth/status").json()["signed_in"] is False
    assert not provider.token_requests or all(
        r["code"] == "the-code" for r in provider.token_requests
    )


@pytest.fixture
def member(client, provider, monkeypatch) -> TestClient:
    monkeypatch.setenv("PCDOCTOR_OAUTH_SIGNUP", "true")
    get_settings.cache_clear()
    visitor = browser(client)
    sign_in(visitor, provider)
    assert visitor.get("/api/auth/status").json()["role"] == "member"
    return visitor


@pytest.mark.parametrize("method, path", MASTER_ONLY)
def test_a_member_is_refused_everything_that_is_the_masters(member, method, path):
    response = getattr(member, method)(path)
    assert response.status_code == 403, f"{method.upper()} {path} answered {response.status_code}"


def test_a_member_sees_only_their_own_runs(client, member, provider):
    masters = client.post("/api/runs", files=run_zip("healthy")).json()["run"]["id"]
    client.post("/api/worklog", json={"title": "Private job", "error_codes": ["0x124"]})
    uploaded = member.post("/api/runs", files=run_zip("whea_bluescreens")).json()
    assert uploaded["share_key"]  # a member is not the master: same limits as a guest
    own = uploaded["run"]["id"]

    assert [r["id"] for r in member.get("/api/me/runs").json()["items"]] == [own]
    detail = member.get(f"/api/me/runs/{own}").json()
    assert detail["findings"] and detail["similar_cases"] == [] and detail["work_log"] == []
    assert member.get(f"/api/me/runs/{own}/series").status_code == 200
    assert member.get(f"/api/me/runs/{masters}").status_code == 404
    assert member.delete(f"/api/me/runs/{masters}").status_code == 404
    assert member.get("/api/stopcodes/0x124").json()["cases"] == []  # not the master's jobs

    # A second member cannot see the first one's run.
    provider.subject = "person-2"
    second = browser(client)
    sign_in(second, provider)
    assert second.get("/api/me/runs").json()["total"] == 0
    assert second.get(f"/api/me/runs/{own}").status_code == 404

    assert client.get("/api/runs").json()["total"] == 2  # the master sees both
    assert member.delete(f"/api/me/runs/{own}").status_code == 204
    assert client.get("/api/runs").json()["total"] == 1


def test_the_master_can_link_a_provider_and_then_sign_in_with_it(client, provider):
    # "link" needs a signed-in browser.
    assert browser(client).get("/api/auth/oauth/discord/start?intent=link").status_code == 401
    master = browser(client)
    master.cookies.update(dict(client.cookies))
    assert sign_in(master, provider, intent="link").headers["location"] == "https://pcdoctor.test/"
    linked = client.get("/api/auth/identities").json()
    assert [i["provider"] for i in linked] == ["discord"]

    visitor = browser(client)  # sign-up is closed, but this identity is known
    sign_in(visitor, provider)
    assert visitor.get("/api/auth/status").json()["role"] == "master"
    assert visitor.get("/api/runs").status_code == 200

    assert client.delete(f"/api/auth/identities/{linked[0]['id']}").status_code == 204
    again = browser(client)
    assert sign_in(again, provider).headers["location"].endswith("problem=not_linked")


def test_the_master_can_list_and_remove_members_but_not_itself(client, member, session):
    accounts = client.get("/api/accounts").json()
    assert [a["role"] for a in accounts] == ["master", "member"]
    assert accounts[1]["providers"] == ["discord"] and "subject" not in accounts[1]
    run_id = member.post("/api/runs", files=run_zip()).json()["run"]["id"]
    assert member.delete("/api/auth/identities/1").status_code == 409  # their only way in
    assert client.delete(f"/api/accounts/{accounts[0]['id']}").status_code == 409
    assert client.delete(f"/api/accounts/{accounts[1]['id']}").status_code == 204
    assert member.get("/api/me/runs").status_code == 401  # their session went with the account
    db = session
    assert db.get(Run, run_id).owner_id is None  # the run stays, without an owner


def test_webhook_gets_the_headline_and_nothing_private(client, guest, monkeypatch, session):
    sent = []

    def fake_post(url, json, timeout):  # noqa: ANN001
        sent.append((url, json))
        return httpx.Response(204, request=httpx.Request("POST", url))

    monkeypatch.setattr(notify.httpx, "post", fake_post)
    monkeypatch.setenv("PCDOCTOR_NOTIFY_WEBHOOK_URL", "https://discord.com/api/webhooks/1/abc")
    get_settings.cache_clear()
    key = guest.post("/api/runs", files=run_zip(), data={"label": "secret label"}).json()[
        "share_key"
    ]
    client.post("/api/runs", files=run_zip("healthy"))  # the master's own upload: no message
    assert len(sent) == 1
    text = sent[0][1]["content"]
    assert text.startswith("New guest run (critical)") and key not in text and "secret" not in text
    assert sent[0][1]["allowed_mentions"] == {"parse": []}

    # A part name comes from the uploaded file: it must not become a link or a ping.
    run = session.scalar(select(Run))
    run.headline = "Disk [click me](https://evil.example) failing @everyone <@123>"
    text = notify.message_for(run)
    assert "](" not in text and "https://" not in text  # escaped: no link
    assert "\\<@" in text and "@everyone" not in text  # escaped: no ping

    monkeypatch.setenv("PCDOCTOR_NOTIFY_WEBHOOK_URL", "http://169.254.169.254/latest")
    get_settings.cache_clear()
    assert notify.new_guest_run(get_settings(), session.scalar(select(Run))) is False
