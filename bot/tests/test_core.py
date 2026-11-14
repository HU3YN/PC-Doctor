"""Tests for the pure module. No Discord token and no network are needed:
every HTTP call goes to an httpx.MockTransport."""

from __future__ import annotations

import asyncio
import io
import logging
import re

import httpx
import pytest

from pcdoctor_bot import core

MB = 1024 * 1024
CDN = "https://cdn.discordapp.com/attachments/1/2/run.zip?ex=abc"
# What Discord would turn into a ping or a channel link.
MENTION = re.compile(r"<[@#][!&]?\d+>|@everyone|@here")
KEY = "k3Jv9Qp_2xZr-7LmN0aBcDeFgHiJkLmNoPqRsTuVwXy"
API = "http://api.test"
PUBLIC = "https://pcdoctor.example"

BASE_ENV = {
    "DISCORD_BOT_TOKEN": "not-a-real-token",
    "DISCORD_GUILD_IDS": "111, 222",
    "PCDOCTOR_URL": "http://api.test/",
}


def run(coro):
    return asyncio.run(coro)


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def diagnosis(**overrides) -> core.Diagnosis:
    values = {
        "verdict": "critical",
        "headline": "The CPU is overheating.",
        "cpu": "Example CPU 8-core",
        "gpu": "Example GPU 12GB",
        "ram_gb": 32,
        "critical_count": 1,
        "warning_count": 2,
        "info_count": 0,
        "findings": (
            core.Finding("critical", "CPU is running hot", "Check the cooler is seated."),
            core.Finding("warning", "Drive nearly full", "Free up space on C:."),
        ),
        "share_key": KEY,
    }
    values.update(overrides)
    return core.Diagnosis(**values)


# ---------------------------------------------------------------- settings


def test_settings_are_read():
    settings = core.load_settings(BASE_ENV)
    assert settings.guild_ids == {111, 222}
    assert settings.api_url == "http://api.test"
    assert settings.public_url == "http://api.test"  # falls back to the API address
    assert settings.max_upload_bytes == 200 * MB
    assert settings.cooldown_seconds == 60


def test_settings_overrides():
    env = BASE_ENV | {
        "PCDOCTOR_PUBLIC_URL": "https://pcdoctor.example/",
        "PCDOCTOR_MAX_UPLOAD_MB": "5",
        "PCDOCTOR_COOLDOWN_SECONDS": "10",
    }
    settings = core.load_settings(env)
    assert settings.public_url == "https://pcdoctor.example"
    assert settings.max_upload_bytes == 5 * MB
    assert settings.cooldown_seconds == 10


@pytest.mark.parametrize("guilds", ["", " ", ",,"])
def test_refuses_to_start_without_an_allow_list(guilds):
    with pytest.raises(core.ConfigError, match="DISCORD_GUILD_IDS"):
        core.load_settings(BASE_ENV | {"DISCORD_GUILD_IDS": guilds})


def test_refuses_to_start_without_a_guild_variable_at_all():
    env = {k: v for k, v in BASE_ENV.items() if k != "DISCORD_GUILD_IDS"}
    with pytest.raises(core.ConfigError, match="DISCORD_GUILD_IDS"):
        core.load_settings(env)


@pytest.mark.parametrize(
    "change",
    [
        {"DISCORD_BOT_TOKEN": ""},
        {"DISCORD_GUILD_IDS": "111,abc"},
        {"PCDOCTOR_URL": ""},
        {"PCDOCTOR_URL": "ftp://api.test"},
        {"PCDOCTOR_MAX_UPLOAD_MB": "0"},
        {"PCDOCTOR_MAX_UPLOAD_MB": "lots"},
        {"PCDOCTOR_COOLDOWN_SECONDS": "-1"},
    ],
)
def test_bad_settings_are_refused(change):
    with pytest.raises(core.ConfigError):
        core.load_settings(BASE_ENV | change)


def test_token_is_not_in_repr_or_error_text():
    settings = core.load_settings(BASE_ENV)
    assert "not-a-real-token" not in repr(settings)
    with pytest.raises(core.ConfigError) as caught:
        core.load_settings(BASE_ENV | {"DISCORD_GUILD_IDS": "x"})
    assert "not-a-real-token" not in str(caught.value)


def test_http_libraries_do_not_log_request_urls():
    # httpx logs each URL at INFO; those hold the share key and the file name.
    core.configure_logging()
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("httpcore").level >= logging.WARNING


# ---------------------------------------------------------------- cooldown


def test_cooldown_is_per_user():
    now = [100.0]
    cooldown = core.Cooldown(60, clock=lambda: now[0])
    assert cooldown.retry_after(1) == 0
    assert cooldown.retry_after(2) == 0  # another person is not held up
    now[0] += 20
    assert cooldown.retry_after(1) == pytest.approx(40)
    now[0] += 41
    assert cooldown.retry_after(1) == 0


def test_a_refused_try_does_not_restart_the_cooldown():
    now = [0.0]
    cooldown = core.Cooldown(60, clock=lambda: now[0])
    cooldown.retry_after(1)
    now[0] = 59
    assert cooldown.retry_after(1) > 0
    now[0] = 61
    assert cooldown.retry_after(1) == 0


def test_cooldown_message_rounds_up():
    assert "1 seconds" in core.format_cooldown(0.2)
    assert "40 seconds" in core.format_cooldown(39.5)


# ------------------------------------------------------- attachment rules


@pytest.mark.parametrize("name", ["run.zip", "PCDoctor-run-1.ZIP", "presentmon.csv", "a.b.Csv"])
def test_zip_and_csv_names_are_accepted(name):
    assert core.check_attachment(name, 10, CDN, MB) in (".zip", ".csv")


@pytest.mark.parametrize(
    "name", ["run.exe", "run.zip.exe", "run", "zip", "run.7z", "run.csv.txt", ""]
)
def test_other_names_are_refused(name):
    with pytest.raises(core.AttachmentError):
        core.check_attachment(name, 10, CDN, MB)


def test_declared_size_is_checked_before_download():
    assert core.check_attachment("run.zip", MB, CDN, MB) == ".zip"
    with pytest.raises(core.AttachmentError, match="limit"):
        core.check_attachment("run.zip", MB + 1, CDN, MB)
    with pytest.raises(core.AttachmentError, match="empty"):
        core.check_attachment("run.zip", 0, CDN, MB)


@pytest.mark.parametrize(
    "url",
    [
        "https://cdn.discordapp.com/attachments/1/2/run.zip",
        "https://media.discordapp.net/attachments/1/2/run.zip?ex=1&is=2",
        "https://cdn.discordapp.com:443/attachments/1/2/run.zip",
    ],
)
def test_discord_hosts_are_accepted(url):
    assert core.check_attachment("run.zip", 10, url, MB) == ".zip"


@pytest.mark.parametrize(
    "url",
    [
        "http://cdn.discordapp.com/attachments/1/2/run.zip",  # not https
        "https://example.com/run.zip",
        "https://cdn.discordapp.com.example.com/run.zip",
        "https://evilcdn.discordapp.com/run.zip",
        "https://example.com/cdn.discordapp.com/run.zip",
        "https://cdn.discordapp.com@example.com/run.zip",
        "https://user:pw@cdn.discordapp.com/run.zip",
        "https://cdn.discordapp.com:8443/run.zip",
        "https://127.0.0.1/run.zip",
        "file:///etc/hostname",
        "//cdn.discordapp.com/run.zip",
        "",
    ],
)
def test_other_addresses_are_refused(url):
    with pytest.raises(core.AttachmentError, match="not hosted by Discord"):
        core.check_attachment("run.zip", 10, url, MB)


# ---------------------------------------------------------------- download


def test_download_returns_the_bytes():
    async def go():
        async with client_for(lambda request: httpx.Response(200, content=b"PK\x03\x04data")) as c:
            data = await core.download_attachment(c, CDN, MB, ".zip")
            return data.read()

    assert run(go()) == b"PK\x03\x04data"


def test_download_stops_at_the_cap_even_if_the_declared_size_lied():
    sent = []

    async def body():
        for _ in range(100):
            sent.append(1)
            yield b"PK" + b"x" * 1022

    async def go():
        # A streamed body has no content-length, so only counting can catch it.
        async with client_for(lambda request: httpx.Response(200, content=body())) as c:
            await core.download_attachment(c, CDN, 10 * 1024, ".zip")

    with pytest.raises(core.AttachmentError, match="limit"):
        run(go())
    assert len(sent) < 100  # gave up early instead of reading everything


def test_download_refuses_a_too_large_content_length():
    async def go():
        async with client_for(
            lambda request: httpx.Response(200, content=b"PK" + b"x" * 5000)
        ) as c:
            await core.download_attachment(c, CDN, 1000, ".zip")

    with pytest.raises(core.AttachmentError, match="limit"):
        run(go())


def test_download_does_not_follow_redirects():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://example.com/other.zip"})

    async def go():
        # Even a client set to follow redirects must not, for this request.
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=True
        ) as c:
            await core.download_attachment(c, CDN, MB, ".zip")

    with pytest.raises(core.AttachmentError):
        run(go())
    assert seen == [CDN]


def test_download_refuses_a_file_that_is_not_a_zip():
    async def go(kind):
        async with client_for(lambda request: httpx.Response(200, content=b"MZ not a zip")) as c:
            return (await core.download_attachment(c, CDN, MB, kind)).read()

    with pytest.raises(core.AttachmentError, match="not a zip"):
        run(go(".zip"))
    assert run(go(".csv")) == b"MZ not a zip"  # csv has no fixed first bytes


def test_download_failures_become_friendly_errors():
    def broken(request):
        raise httpx.ConnectError("no route")

    async def go(handler):
        async with client_for(handler) as c:
            await core.download_attachment(c, CDN, MB, ".zip")

    with pytest.raises(core.AttachmentError, match="could not be downloaded"):
        run(go(broken))
    with pytest.raises(core.AttachmentError, match="hand over"):
        run(go(lambda request: httpx.Response(404)))
    with pytest.raises(core.AttachmentError, match="empty"):
        run(go(lambda request: httpx.Response(200, content=b"")))


# ---------------------------------------------------------------- the API


RUN = {
    "id": "run-1",
    "verdict": "warning",
    "headline": "Two things need attention.",
    "critical_count": 0,
    "warning_count": 2,
    "info_count": 1,
    "cpu": "Example CPU",
    "gpu": "Example GPU",
    "ram_gb": 16,
}
FINDINGS = [
    {
        "code": "a",
        "category": "x",
        "severity": "info",
        "title": "Note",
        "summary": "",
        "next_checks": [],
    },
    {
        "code": "b",
        "category": "x",
        "severity": "warning",
        "title": "Warm GPU",
        "summary": "",
        "next_checks": ["Clean the fans.", "Later."],
    },
    {
        "code": "c",
        "category": "x",
        "severity": "critical",
        "title": "Failing disk",
        "summary": "",
        "next_checks": ["Back up now."],
    },
    {
        "code": "d",
        "category": "x",
        "severity": "warning",
        "title": "Old driver",
        "summary": "",
        "next_checks": ["Update it."],
    },
]


def test_upload_flow_end_to_end():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST" and request.url.path == "/api/runs":
            return httpx.Response(201, json={"run": RUN, "duplicate": False, "share_key": KEY})
        if request.method == "GET" and request.url.path == f"/api/shared/{KEY}":
            return httpx.Response(200, json={"findings": FINDINGS})
        return httpx.Response(404, json={"detail": "nope"})

    async def go():
        async with client_for(handler) as c:
            return await core.diagnose(c, API, io.BytesIO(b"PK-zip-bytes"), ".zip", "my label")

    result = run(go())
    assert [r.method for r in requests] == ["POST", "GET"]
    upload = requests[0].content
    assert requests[0].headers["content-type"].startswith("multipart/form-data")
    assert b'name="file"; filename="run.zip"' in upload  # fixed name, not the person's
    assert b"PK-zip-bytes" in upload
    assert b'name="label"' in upload and b"my label" in upload
    assert result.verdict == "warning"
    assert result.share_key == KEY
    assert (result.cpu, result.gpu, result.ram_gb) == ("Example CPU", "Example GPU", 16)
    # Most serious first, three at most, with the first next check only.
    assert [f.title for f in result.findings] == ["Failing disk", "Warm GPU", "Old driver"]
    assert result.findings[1].first_check == "Clean the fans."


def test_the_bot_token_goes_with_the_upload_only():
    seen = []

    def handler(request):
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(201, json={"run": RUN, "duplicate": False, "share_key": KEY})
        return httpx.Response(200, json={"findings": FINDINGS})

    async def go():
        async with client_for(handler) as c:
            return await core.diagnose(c, API, io.BytesIO(b"PK"), ".zip", api_token="bot-secret")

    run(go())
    assert seen[0].headers[core.BOT_TOKEN_HEADER] == "bot-secret"
    assert core.BOT_TOKEN_HEADER not in seen[1].headers  # never sent to read findings


def test_no_bot_token_header_without_a_token():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"run": RUN, "duplicate": True, "share_key": None})

    async def go():
        async with client_for(handler) as c:
            return await core.diagnose(c, API, io.BytesIO(b"PK"), ".zip")

    run(go())
    assert core.BOT_TOKEN_HEADER not in seen[0].headers


def test_the_bot_token_is_read_and_kept_out_of_repr():
    settings = core.load_settings(BASE_ENV | {"PCDOCTOR_BOT_TOKEN": " bot-secret "})
    assert settings.api_token == "bot-secret"
    assert "bot-secret" not in repr(settings)
    assert core.load_settings(BASE_ENV).api_token == ""


def test_no_label_field_is_sent_when_there_is_no_label():
    seen = []

    def handler(request):
        seen.append(request.content)
        return httpx.Response(200, json={"run": RUN, "duplicate": True, "share_key": None})

    async def go():
        async with client_for(handler) as c:
            return await core.diagnose(c, API, io.BytesIO(b"a,b\n1,2\n"), ".csv")

    result = run(go())
    assert len(seen) == 1  # no key, so no second request
    assert b'name="label"' not in seen[0]
    assert b'filename="run.csv"' in seen[0]
    assert result.share_key is None and result.duplicate and result.findings == ()


def test_summary_still_arrives_when_findings_cannot_be_read():
    def handler(request):
        if request.method == "POST":
            return httpx.Response(201, json={"run": RUN, "duplicate": False, "share_key": KEY})
        return httpx.Response(500, text="boom")

    async def go():
        async with client_for(handler) as c:
            return await core.diagnose(c, API, io.BytesIO(b"PK"), ".zip")

    result = run(go())
    assert result.headline == RUN["headline"] and result.findings == ()


@pytest.mark.parametrize(
    "bad_key", ["../../admin", "a/b" * 10, "short", "x" * 500, 12345, "key with spaces 123456"]
)
def test_an_odd_share_key_is_never_put_in_a_url(bad_key):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(201, json={"run": RUN, "duplicate": False, "share_key": bad_key})

    async def go():
        async with client_for(handler) as c:
            return await core.diagnose(c, API, io.BytesIO(b"PK"), ".zip")

    result = run(go())
    assert result.share_key is None
    assert paths == ["/api/runs"]
    assert "private link" not in core.format_reply(result, PUBLIC).split("\n\n")[-1].replace(
        "No private link", ""
    )


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (400, {"detail": "The zip file is damaged and cannot be opened."}, "damaged"),
        (400, {"detail": [{"msg": "structured"}]}, "could not read that file"),
        (413, {"detail": "The file is larger than the 200 MB limit."}, "200 MB limit"),
        (413, None, "too large"),
        (
            429,
            {"detail": "Too many uploads from here. Try again in an hour."},
            "Try again in an hour",
        ),
        (500, {"detail": "Traceback: secret internals"}, "had a problem"),
        (502, None, "had a problem"),
    ],
)
def test_api_errors_become_friendly_messages(status, body, expected):
    def handler(request):
        if body is None:
            return httpx.Response(status, text="<html>gateway</html>")
        return httpx.Response(status, json=body)

    async def go():
        async with client_for(handler) as c:
            await core.diagnose(c, API, io.BytesIO(b"PK"), ".zip")

    with pytest.raises(core.ApiError) as caught:
        run(go())
    message = str(caught.value)
    assert expected in message
    assert "secret internals" not in message and "<html>" not in message


def test_unreachable_api_and_nonsense_answers():
    def down(request):
        raise httpx.ConnectError("refused")

    async def go(handler):
        async with client_for(handler) as c:
            await core.diagnose(c, API, io.BytesIO(b"PK"), ".zip")

    with pytest.raises(core.ApiError, match="could not be reached"):
        run(go(down))
    with pytest.raises(core.ApiError, match="did not understand"):
        run(go(lambda request: httpx.Response(200, text="not json")))
    with pytest.raises(core.ApiError, match="did not understand"):
        run(go(lambda request: httpx.Response(200, json=["a list"])))


def test_top_findings_ignores_junk():
    assert core.top_findings(None) == ()
    assert core.top_findings({"not": "a list"}) == ()
    raw = [
        "text",
        {"severity": "critical"},
        {"title": "Real", "severity": "odd", "next_checks": "x"},
    ]
    assert core.top_findings(raw) == (core.Finding("odd", "Real", ""),)


# ---------------------------------------------------------------- reply text


def test_private_reply_has_everything():
    text = core.format_reply(diagnosis(), PUBLIC)
    assert "Critical problems found" in text
    assert "The CPU is overheating." in text
    assert "Example CPU 8\\-core / Example GPU 12GB / 32 GB RAM" in text
    assert "1. **CPU is running hot**" in text
    assert "Check first: Check the cooler is seated." in text
    assert "2. **Drive nearly full**" in text
    assert text.endswith(f"<{PUBLIC}/r/{KEY}>")


def test_public_reply_has_no_private_link():
    text = core.format_reply(diagnosis(), PUBLIC, public=True, label="desk PC")
    assert KEY not in text
    assert "/r/" not in text
    assert "pcdoctor.example" not in text
    assert "http" not in text
    # ...but it is still a useful summary.
    assert "CPU is running hot" in text and "desk PC" in text


def test_public_reply_stays_clean_when_truncated():
    many = tuple(core.Finding("warning", "T" * 150, "C" * 300) for _ in range(3))
    text = core.format_reply(
        diagnosis(findings=many, headline="H" * 300), PUBLIC, public=True, limit=400
    )
    assert len(text) <= 400
    assert KEY not in text and "/r/" not in text


def test_long_reply_is_cut_to_the_limit_and_keeps_the_link_whole():
    many = tuple(core.Finding("warning", "*" * 150, "_" * 300) for _ in range(3))
    text = core.format_reply(
        diagnosis(findings=many, headline="#" * 300, cpu="[" * 80, gpu="|" * 80),
        PUBLIC,
        label="@" * 200,
    )
    assert len(text) <= core.DISCORD_MESSAGE_LIMIT
    assert "…" in text
    assert text.endswith(f"<{PUBLIC}/r/{KEY}>")


@pytest.mark.parametrize("limit", range(150, 420, 7))
def test_truncation_never_goes_over_or_ends_on_a_backslash(limit):
    text = core.format_reply(diagnosis(headline="*_" * 150), PUBLIC, limit=limit)
    assert len(text) <= limit
    body = text.split("\n\nFull report")[0]
    assert not body.removesuffix("…").endswith("\\")
    assert text.endswith(f"<{PUBLIC}/r/{KEY}>")


def test_reply_without_a_key_says_so():
    text = core.format_reply(diagnosis(share_key=None), PUBLIC)
    assert "No private link" in text and "/r/" not in text


def test_reply_copes_with_missing_parts():
    text = core.format_reply(
        diagnosis(verdict="ok", cpu=None, gpu=None, ram_gb=None, findings=(), headline=""), PUBLIC
    )
    assert "No problems found" in text
    assert "Build:" not in text and "Top findings" not in text


def test_unknown_verdict_is_not_echoed():
    text = core.format_reply(diagnosis(verdict="@everyone"), PUBLIC)
    assert "everyone" not in text


def test_link_note_holds_the_link():
    assert f"<{PUBLIC}/r/{KEY}>" in core.format_link_note(PUBLIC, KEY)


# ---------------------------------------------------------------- escaping


@pytest.mark.parametrize(
    "text",
    ["@everyone", "@here", "<@123456789>", "<@!123456789>", "<@&987654321>", "<#555>"],
)
def test_mentions_are_defused(text):
    escaped = core.escape(text)
    assert MENTION.search(text)  # the pattern does catch the raw text
    assert not MENTION.search(escaped)


def test_markdown_and_links_are_defused():
    assert core.escape("**bold** _it_ `code` ~~no~~ ||spoiler||") == (
        "\\*\\*bold\\*\\* \\_it\\_ \\`code\\` \\~\\~no\\~\\~ \\|\\|spoiler\\|\\|"
    )
    assert "https://" not in core.escape("see https://example.com/x")
    assert "](" not in core.escape("[click](https://example.com)")
    assert core.escape("# heading\n> quote\n- item") == "\\# heading \\> quote \\- item"
    assert core.escape("back\\slash") == "back\\\\slash"


def test_escape_flattens_and_caps():
    assert core.escape("a\n\n\nb\t c\x00​‮") == "a b c"
    capped = core.escape("x" * 500, 50)
    assert len(capped) == 50 and capped.endswith("…")


def test_label_in_the_reply_cannot_ping_or_format():
    label = "@everyone **free** <@&1> [x](https://example.com)\n# big"
    for public in (False, True):
        text = core.format_reply(diagnosis(), PUBLIC, public=public, label=label)
        line = next(part for part in text.split("\n") if part.startswith("Label: "))
        assert not MENTION.search(line)
        assert "**" not in line and "](" not in line and "https://" not in line
        assert "big" in line  # the newline did not start a line of its own


def test_text_from_the_api_is_escaped_too():
    hostile = diagnosis(
        headline="@here look",
        cpu="<@&42>",
        gpu="https://example.com",
        findings=(core.Finding("critical", "**@everyone**", "[go](https://example.com)"),),
    )
    text = core.format_reply(hostile, PUBLIC, public=True)
    assert not MENTION.search(text)
    assert "https://" not in text and "](" not in text


def test_error_text_is_escaped_and_capped():
    text = core.format_error(core.ApiError("@everyone " + "x" * 5000))
    assert "@everyone" not in text and len(text) <= core.DISCORD_MESSAGE_LIMIT
