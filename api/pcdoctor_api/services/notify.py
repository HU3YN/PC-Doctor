"""Tell the master, through a Discord webhook, that a guest sent a run.

Optional (PCDOCTOR_NOTIFY_WEBHOOK_URL). Only the verdict and the headline are
sent - never the private link, a label, or anything about who sent it.
"""

from __future__ import annotations

import re

import httpx

from ..config import Settings
from ..models import Run

ALLOWED_PREFIXES = ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/")


# Characters Discord reads as formatting, links ("[text](url)", "https://"),
# mentions ("<@id>") or emoji (":name:"). Same list as the bot's own escape.
_MARKDOWN = re.compile(r"([\\*_~`|>#\[\]()<:\-])")


def escape(text: str, limit: int = 300) -> str:
    """Make upload text harmless in a Discord message. A headline can hold a
    part name taken from the uploaded file, so a stranger chooses part of it."""
    text = "".join(ch for ch in text if ch.isprintable())
    text = " ".join(text.split())[:limit]
    text = _MARKDOWN.sub(r"\\\1", text)
    return text.replace("@", "@\u200b")  # a zero-width space breaks @everyone


def message_for(run: Run) -> str:
    return f"New guest run ({escape(run.verdict, 20)}): {escape(run.headline)}"[:1900]


def new_guest_run(settings: Settings, run: Run) -> bool:
    url = settings.notify_webhook_url
    if not url or not url.startswith(ALLOWED_PREFIXES):
        return False
    try:
        # allowed_mentions: a headline can never ping anyone.
        body = {"content": message_for(run), "allowed_mentions": {"parse": []}}
        httpx.post(url, json=body, timeout=5.0).raise_for_status()
    except httpx.HTTPError:
        return False  # a notification failing must never fail an upload
    return True
