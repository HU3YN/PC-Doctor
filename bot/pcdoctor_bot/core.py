"""Everything the bot does that does not need Discord.

Settings, attachment rules, the download, the PC Doctor API client and the
reply text live here so they can be tested without a token or a network.
"""

from __future__ import annotations

import logging
import re
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import IO, Any
from urllib.parse import urlsplit

import httpx

# Discord rejects messages longer than this.
DISCORD_MESSAGE_LIMIT = 2000

# Discord serves attachments from these hosts only. Anything else is refused,
# so the bot can never be made to fetch an arbitrary address.
ALLOWED_ATTACHMENT_HOSTS = frozenset({"cdn.discordapp.com", "media.discordapp.net"})
ALLOWED_EXTENSIONS = (".zip", ".csv")

DEFAULT_MAX_UPLOAD_MB = 200
DEFAULT_COOLDOWN_SECONDS = 60
MAX_LABEL_LENGTH = 200  # the API's own limit for the label field
TOP_FINDINGS = 3

# The key goes into a URL path, so accept only the URL-safe token alphabet.
_SHARE_KEY = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
_VERDICT_TEXT = {
    "critical": "Critical problems found",
    "warning": "Needs attention",
    "ok": "No problems found",
}


class ConfigError(Exception):
    """The environment is not set up. The message names the variable, never its value."""


class UserError(Exception):
    """Something went wrong that the requester can be told about as-is."""


class AttachmentError(UserError):
    """The attachment breaks one of the rules."""


class ApiError(UserError):
    """The PC Doctor API refused the upload or could not be reached."""


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    # repr=False keeps the token out of logs and tracebacks that print the object.
    token: str = field(repr=False)
    guild_ids: frozenset[int]
    api_url: str
    public_url: str
    max_upload_bytes: int
    cooldown_seconds: float
    # PCDOCTOR_BOT_TOKEN: lets the API count the bot's uploads against their
    # own, higher limit. Optional. It is sent with uploads only.
    api_token: str = field(default="", repr=False)


def _base_url(name: str, value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ConfigError(f"{name} must be an http(s) address.")
    return value.rstrip("/")


def _positive_number(name: str, raw: str | None, default: float) -> float:
    if raw is None or not raw.strip():
        return default
    try:
        number = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number.") from None
    if number <= 0:
        raise ConfigError(f"{name} must be greater than zero.")
    return number


def load_settings(env: Mapping[str, str]) -> Settings:
    """Read the bot's settings. Raises ConfigError rather than starting half set up."""
    token = env.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError("DISCORD_BOT_TOKEN is not set.")

    guild_ids: set[int] = set()
    for part in env.get("DISCORD_GUILD_IDS", "").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise ConfigError("DISCORD_GUILD_IDS must be server IDs (numbers), comma separated.")
        guild_ids.add(int(part))
    if not guild_ids:
        # Project rule: the bot works only in servers whose moderators approved it.
        raise ConfigError(
            "DISCORD_GUILD_IDS is empty. List the approved server IDs; the bot will not "
            "start without an allow-list."
        )

    api_url = _base_url("PCDOCTOR_URL", env.get("PCDOCTOR_URL", "").strip())
    public_raw = env.get("PCDOCTOR_PUBLIC_URL", "").strip()
    public_url = _base_url("PCDOCTOR_PUBLIC_URL", public_raw) if public_raw else api_url

    max_mb = _positive_number(
        "PCDOCTOR_MAX_UPLOAD_MB", env.get("PCDOCTOR_MAX_UPLOAD_MB"), DEFAULT_MAX_UPLOAD_MB
    )
    cooldown = _positive_number(
        "PCDOCTOR_COOLDOWN_SECONDS", env.get("PCDOCTOR_COOLDOWN_SECONDS"), DEFAULT_COOLDOWN_SECONDS
    )
    return Settings(
        token=token,
        guild_ids=frozenset(guild_ids),
        api_url=api_url,
        public_url=public_url,
        max_upload_bytes=int(max_mb * 1024 * 1024),
        cooldown_seconds=cooldown,
        api_token=env.get("PCDOCTOR_BOT_TOKEN", "").strip(),
    )


def configure_logging() -> None:
    """Plain logging, with the HTTP libraries turned down.

    httpx logs every request URL at INFO. Those URLs hold the private share
    key and the attachment's file name, so they must not reach the log.
    """
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


# --------------------------------------------------------------------------
# Cooldown
# --------------------------------------------------------------------------


class Cooldown:
    """One use per key per period. Kept in memory only; nothing is written down."""

    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._seconds = seconds
        self._clock = clock
        self._last: dict[int, float] = {}

    def retry_after(self, key: int) -> float:
        """0 if the key may go now (and starts its cooldown), else seconds left."""
        now = self._clock()
        last = self._last.get(key)
        if last is not None and now - last < self._seconds:
            return self._seconds - (now - last)
        # Forget expired entries so the table does not grow for ever.
        if len(self._last) > 1000:
            self._last = {k: t for k, t in self._last.items() if now - t < self._seconds}
        self._last[key] = now
        return 0.0


# --------------------------------------------------------------------------
# Attachment rules and download
# --------------------------------------------------------------------------


def _megabytes(size: int) -> str:
    return f"{size / (1024 * 1024):.0f} MB"


def attachment_kind(filename: str) -> str:
    """Return ".zip" or ".csv", or raise if the name is anything else."""
    lowered = filename.lower()
    for extension in ALLOWED_EXTENSIONS:
        if lowered.endswith(extension):
            return extension
    raise AttachmentError(
        "Attach the .zip file the PC Doctor collector made, or a PresentMon .csv file."
    )


def check_attachment(filename: str, size: int, url: str, max_bytes: int) -> str:
    """Check an attachment BEFORE anything is downloaded. Returns its kind."""
    kind = attachment_kind(filename)
    if size <= 0:
        raise AttachmentError("That file is empty.")
    if size > max_bytes:
        raise AttachmentError(
            f"That file is {_megabytes(size)}; the limit is {_megabytes(max_bytes)}."
        )
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_ATTACHMENT_HOSTS:
        raise AttachmentError("That attachment is not hosted by Discord, so it was not opened.")
    # A port or user:password part has no place in a Discord attachment link.
    if parts.port not in (None, 443) or parts.username or parts.password:
        raise AttachmentError("That attachment is not hosted by Discord, so it was not opened.")
    return kind


async def download_attachment(
    client: httpx.AsyncClient, url: str, max_bytes: int, kind: str
) -> IO[bytes]:
    """Stream the attachment into a temporary file, stopping at the size cap.

    The declared size was already checked, but it is only a claim, so the
    bytes are counted as they arrive. Redirects are not followed: a redirect
    could lead away from Discord's hosts.
    """
    target = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)  # noqa: SIM115
    try:
        async with client.stream("GET", url, follow_redirects=False) as response:
            if response.status_code != 200:
                raise AttachmentError("Discord would not hand over that file. Attach it again.")
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > max_bytes:
                raise AttachmentError(f"That file is over the {_megabytes(max_bytes)} limit.")
            received = 0
            async for chunk in response.aiter_bytes():
                received += len(chunk)
                if received > max_bytes:
                    raise AttachmentError(f"That file is over the {_megabytes(max_bytes)} limit.")
                target.write(chunk)
        if received == 0:
            raise AttachmentError("That file is empty.")
        target.seek(0)
        # Every zip starts with "PK". This catches a renamed file early.
        if kind == ".zip" and target.read(2) != b"PK":
            raise AttachmentError("That file is not a zip. Attach the .zip the collector made.")
        target.seek(0)
        return target
    except httpx.HTTPError:
        target.close()
        raise AttachmentError("The file could not be downloaded from Discord. Try again.") from None
    except BaseException:
        target.close()
        raise


# --------------------------------------------------------------------------
# PC Doctor API
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    severity: str
    title: str
    first_check: str


@dataclass(frozen=True)
class Diagnosis:
    verdict: str
    headline: str
    cpu: str | None
    gpu: str | None
    ram_gb: int | None
    critical_count: int
    warning_count: int
    info_count: int
    findings: tuple[Finding, ...]
    # None when the API gave no usable key; the reply then has no link.
    share_key: str | None = field(repr=False)
    duplicate: bool = False


def _error_detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return ""
    return detail if isinstance(detail, str) else ""


def _api_error(response: httpx.Response) -> ApiError:
    """Turn an API error answer into a sentence for the requester."""
    status = response.status_code
    detail = _error_detail(response)
    if status == 400:
        # The API writes these messages for end users ("The zip file is damaged...").
        return ApiError(detail or "PC Doctor could not read that file.")
    if status == 413:
        return ApiError(detail or "That file is too large for PC Doctor.")
    if status == 429:
        return ApiError(
            "PC Doctor has had too many uploads from this bot for now. Try again in an hour."
        )
    return ApiError("PC Doctor had a problem checking that file. Try again later.")


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def top_findings(raw: Any, limit: int = TOP_FINDINGS) -> tuple[Finding, ...]:
    """The most serious findings first; the API's own order breaks ties."""
    if not isinstance(raw, list):
        return ()
    findings = []
    for item in raw:
        if not isinstance(item, dict) or not _text(item.get("title")):
            continue
        checks = item.get("next_checks")
        first = _text(checks[0]) if isinstance(checks, list) and checks else ""
        findings.append(Finding(_text(item.get("severity")), item["title"], first))
    findings.sort(key=lambda f: _SEVERITY_ORDER.get(f.severity, len(_SEVERITY_ORDER)))
    return tuple(findings[:limit])


BOT_TOKEN_HEADER = "X-PCDoctor-Bot-Token"


async def upload_run(
    client: httpx.AsyncClient,
    api_url: str,
    data: IO[bytes],
    kind: str,
    label: str = "",
    api_token: str = "",
) -> dict[str, Any]:
    """Upload a run as a guest and return the API's answer. With the bot token,
    the API counts the upload against the bot's own limit (it is still a guest
    upload: the token cannot read anything)."""
    # A fixed name is sent on purpose: the person's own file name can hold
    # personal details and the API does not need it.
    files = {"file": (f"run{kind}", data, "application/octet-stream")}
    form = {"label": label[:MAX_LABEL_LENGTH]} if label else {}
    try:
        headers = {BOT_TOKEN_HEADER: api_token} if api_token else {}
        response = await client.post(f"{api_url}/api/runs", files=files, data=form, headers=headers)
    except httpx.HTTPError:
        raise ApiError("PC Doctor could not be reached. Try again later.") from None
    if response.status_code not in (200, 201):
        raise _api_error(response)
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or not isinstance(body.get("run"), dict):
        raise ApiError("PC Doctor gave an answer the bot did not understand. Try again later.")
    return body


async def fetch_findings(client: httpx.AsyncClient, api_url: str, share_key: str) -> Any:
    """Read the findings of one run through its private key. Returns [] on any failure:
    the summary from the upload is still worth showing without them."""
    try:
        response = await client.get(f"{api_url}/api/shared/{share_key}")
        if response.status_code != 200:
            return []
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return []
    return body.get("findings", []) if isinstance(body, dict) else []


async def diagnose(
    client: httpx.AsyncClient,
    api_url: str,
    data: IO[bytes],
    kind: str,
    label: str = "",
    api_token: str = "",
) -> Diagnosis:
    """Upload a run, then read its findings."""
    body = await upload_run(client, api_url, data, kind, label, api_token)
    run = body["run"]
    share_key = body.get("share_key")
    if not isinstance(share_key, str) or not _SHARE_KEY.fullmatch(share_key):
        share_key = None
    findings = await fetch_findings(client, api_url, share_key) if share_key else []
    ram = run.get("ram_gb")
    return Diagnosis(
        verdict=_text(run.get("verdict")),
        headline=_text(run.get("headline")),
        cpu=_text(run.get("cpu")) or None,
        gpu=_text(run.get("gpu")) or None,
        ram_gb=ram if isinstance(ram, int) and not isinstance(ram, bool) else None,
        critical_count=_count(run.get("critical_count")),
        warning_count=_count(run.get("warning_count")),
        info_count=_count(run.get("info_count")),
        findings=top_findings(findings),
        share_key=share_key,
        duplicate=bool(body.get("duplicate")),
    )


# --------------------------------------------------------------------------
# Reply text
# --------------------------------------------------------------------------

_MARKDOWN = re.compile(r"([\\*_~`|>#\[\]()<:\-])")
_WHITESPACE = re.compile(r"\s+")


def escape(text: str, limit: int = 300) -> str:
    """Make text that came from an upload safe to put in a Discord message.

    The label, the part names and (through them) the findings all come from a
    file a stranger sent. Escaping stops that text from formatting the reply,
    pinging anyone (@everyone, <@id>, <@&role>) or showing up as a link.
    The bot also sends with allowed_mentions set to none; this is the second lock.
    """
    # One line, no control or invisible characters.
    text = "".join(ch for ch in text if ch.isprintable() or ch.isspace())
    text = _WHITESPACE.sub(" ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    # Escaping ":" and "<" also breaks "https://" autolinks, <@mentions> and :emoji:.
    text = _MARKDOWN.sub(r"\\\1", text)
    # A zero-width space after "@" stops @everyone and @here.
    return text.replace("@", "@​")


def _build_line(diagnosis: Diagnosis) -> str:
    parts = [escape(part, 80) for part in (diagnosis.cpu, diagnosis.gpu) if part]
    if diagnosis.ram_gb:
        parts.append(f"{diagnosis.ram_gb} GB RAM")
    return " / ".join(parts)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: max(limit - 1, 0)].rstrip()
    # Do not end on half an escape: a lone backslash would escape the "…".
    while cut.endswith("\\"):
        cut = cut[:-1]
    return cut + "…"


def private_link(public_url: str, share_key: str) -> str:
    return f"{public_url}/r/{share_key}"


def format_reply(
    diagnosis: Diagnosis,
    public_url: str,
    *,
    public: bool = False,
    label: str = "",
    limit: int = DISCORD_MESSAGE_LIMIT,
) -> str:
    """The reply for /diagnose.

    The private version ends with the private link. The public version never
    contains the link or the key: anyone holding the link can open the run.
    """
    verdict = _VERDICT_TEXT.get(diagnosis.verdict, "Checked")
    lines = [f"**PC Doctor: {verdict}**"]
    if label:
        lines.append(f"Label: {escape(label, MAX_LABEL_LENGTH)}")
    if diagnosis.headline:
        lines.append(escape(diagnosis.headline))
    build = _build_line(diagnosis)
    if build:
        lines.append(f"Build: {build}")
    lines.append(
        f"{diagnosis.critical_count} critical, {diagnosis.warning_count} warnings, "
        f"{diagnosis.info_count} notes"
    )
    if diagnosis.findings:
        lines.append("")
        lines.append("**Top findings**")
        for number, finding in enumerate(diagnosis.findings, start=1):
            lines.append(f"{number}. **{escape(finding.title, 150)}**")
            if finding.first_check:
                lines.append(f"   Check first: {escape(finding.first_check)}")
    body = "\n".join(lines)

    if public:
        footer = "\n\nThe full report is private to the person who ran this."
    elif diagnosis.share_key:
        link = private_link(public_url, diagnosis.share_key)
        # <...> stops Discord from building a preview of the private page.
        footer = f"\n\nFull report (private link - anyone who has it can open it): <{link}>"
    else:
        footer = "\n\nNo private link was given for this run."
    # Cut the findings, never the footer: the link must arrive whole.
    return _truncate(body, limit - len(footer)) + footer


def format_link_note(public_url: str, share_key: str) -> str:
    """Sent only to the requester after a public reply, so they still get their link."""
    link = private_link(public_url, share_key)
    return f"Your private link to the full report (only you can see this message): <{link}>"


def format_error(error: UserError, limit: int = DISCORD_MESSAGE_LIMIT) -> str:
    """An error sentence for the requester. API text is escaped like any upload text."""
    return _truncate(escape(str(error), 500), limit)


def format_cooldown(seconds_left: float) -> str:
    return f"Please wait {max(int(seconds_left + 0.999), 1)} seconds before using /diagnose again."
