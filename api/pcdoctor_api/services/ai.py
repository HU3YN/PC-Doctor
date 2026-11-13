"""The AI helper: describes a photo and drafts a work-log entry.

Optional. It runs only when an API key is configured AND the master presses
the button - nothing is sent anywhere automatically. When it runs, the text
(and, for a photo, the photo) is sent to Anthropic's API.

The helper drafts; the technician decides. Its output is checked against the
allowed fields and categories, and it is told never to invent a cause or a fix.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any

from pcdoctor_analysis.model import CATEGORIES

from ..config import Settings

DRAFT_FIELDS = ("title", "category", "symptoms", "steps", "root_cause", "fix")
LIST_FIELDS = ("error_codes", "components")

RULES = (
    "You help a PC repair technician keep an accurate work log. "
    "Use only what is in the material you are given. Never invent a stop code, a part, "
    "a cause or a fix: if something is not stated or visible, leave that field empty. "
    "Never include names of people, phone numbers, email addresses or serial numbers. "
    "Write plainly and briefly, the way a technician writes notes. "
    "Answer with one JSON object and nothing else."
)
DRAFT_SHAPE = (
    'Fields: "title" (one line, under 100 characters), "category" (one of: '
    + ", ".join(CATEGORIES)
    + '), "symptoms", "steps" (what was checked or found), "root_cause", "fix", '
    '"error_codes" (list of strings), "components" (list of part names). '
    'Leave "root_cause" and "fix" empty unless the technician\'s own notes state them.'
)
PHOTO_SHAPE = (
    'Fields: "summary" (one or two sentences on what the photo shows), "observations" '
    "(list: lit debug LEDs and their labels, codes on a display, error text, visible damage "
    'such as burn marks, bulged capacitors, bent pins, loose plugs), "error_codes" (list of '
    'codes you can actually read), "category" (one of: '
    + ", ".join(CATEGORIES)
    + ', or "" if unclear), "next_checks" (list, most useful first), "uncertain" (list of '
    "things you could not make out)."
)


class AiUnavailable(RuntimeError):
    """No key, or the SDK is not installed."""


class AiError(RuntimeError):
    """The helper was asked but could not give a usable answer."""


def available(settings: Settings) -> bool:
    if not settings.anthropic_api_key:
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def _client(settings: Settings):
    if not settings.anthropic_api_key:
        raise AiUnavailable("The AI helper is off: no ANTHROPIC_API_KEY is set on this server.")
    try:
        import anthropic
    except ImportError as error:
        raise AiUnavailable(
            "The AI helper is not installed on this server (pip install 'pcdoctor-api[ai]')."
        ) from error
    return anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=60.0, max_retries=1)


def parse_json(text: str) -> dict[str, Any]:
    """The JSON object in a model's reply, tolerating code fences and stray text."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise AiError("The AI helper did not answer in the expected form. Try again.")
    try:
        value = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        raise AiError("The AI helper did not answer in the expected form. Try again.") from None
    if not isinstance(value, dict):
        raise AiError("The AI helper did not answer in the expected form. Try again.")
    return value


def _strings(value: Any, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:300] for item in value if str(item).strip()][:limit]


def clean_draft(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep only known fields, with sane sizes and a real category."""
    draft: dict[str, Any] = {}
    for name in DRAFT_FIELDS:
        value = raw.get(name)
        draft[name] = str(value).strip()[:4000] if isinstance(value, (str, int, float)) else ""
    draft["title"] = " ".join(draft["title"].split())[:200]
    if draft["category"] not in CATEGORIES:
        draft["category"] = "other"
    for name in LIST_FIELDS:
        draft[name] = [item[:80] for item in _strings(raw.get(name))]
    return draft


def clean_photo_notes(raw: dict[str, Any]) -> dict[str, Any]:
    category = raw.get("category")
    return {
        "summary": str(raw.get("summary") or "").strip()[:1000],
        "observations": _strings(raw.get("observations")),
        "error_codes": [item[:40] for item in _strings(raw.get("error_codes"))],
        "category": category if category in CATEGORIES else "",
        "next_checks": _strings(raw.get("next_checks")),
        "uncertain": _strings(raw.get("uncertain")),
    }


def _ask(settings: Settings, content: Any, shape: str) -> dict[str, Any]:
    client = _client(settings)
    try:
        reply = client.messages.create(
            model=settings.ai_model,
            # Room for the model's own reasoning as well as the short answer.
            max_tokens=8000,
            output_config={"effort": "low"},
            system=f"{RULES}\n\n{shape}",
            messages=[{"role": "user", "content": content}],
        )
    except Exception as error:  # noqa: BLE001 - any SDK failure becomes one clear message
        raise AiError(f"The AI helper could not be reached ({error.__class__.__name__}).") from None
    stop = getattr(reply, "stop_reason", None)
    if stop == "refusal":
        raise AiError("The AI helper declined to answer this one.")
    if stop == "max_tokens":
        raise AiError("The AI helper's answer was cut off. Try again.")
    text = "".join(getattr(block, "text", "") or "" for block in reply.content)
    return parse_json(text)


def draft_entry(settings: Settings, material: str) -> dict[str, Any]:
    return clean_draft(_ask(settings, material[:20000], DRAFT_SHAPE))


def describe_photo(settings: Settings, jpeg: bytes, ocr_text: str) -> dict[str, Any]:
    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.b64encode(jpeg).decode(),
            },
        },
        {
            "type": "text",
            "text": "A photo of a PC that will not start, or of its error screen. "
            f"Text an OCR program read from it (may be wrong or empty):\n{ocr_text[:3000]}",
        },
    ]
    return clean_photo_notes(_ask(settings, content, PHOTO_SHAPE))


# --- the troubleshooter -----------------------------------------------------

TROUBLESHOOT_SHAPE = (
    "You are given the automatic findings for one PC, each with a code in square brackets, "
    "and sometimes the technician's own earlier jobs. Work out the single most likely root "
    "cause and how to confirm it. "
    'Fields: "likely_cause" (one or two sentences), "category" (one of: '
    + ", ".join(CATEGORIES)
    + '), "confidence" ("low", "medium" or "high"), "because" (list of objects with '
    '"finding" - a finding code copied exactly from the material - and "why"), '
    '"steps" (list: the checks to do, cheapest and most telling first; say what result '
    'confirms or rules out the cause), "rule_out" (list: other causes that fit and how to '
    'tell them apart), "missing" (list: data that was not collected and would help). '
    "Every claim must rest on a finding in the material. If the findings do not point to a "
    'cause, say so in "likely_cause", use confidence "low" and category "no_fault_found" or '
    '"other". Never suggest anything that risks the hardware (no overvolting, no blocking '
    "cooling) and never suggest changing settings without saying how to put them back."
)
CONFIDENCE = ("low", "medium", "high")


def clean_troubleshoot(raw: dict[str, Any], known_codes: set[str]) -> dict[str, Any]:
    """Keep only what can be checked. A reason must cite a finding this run
    really has; an answer left with no such reason is marked low confidence."""
    because = []
    items = raw.get("because")
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("finding") or "").strip()
        why = str(item.get("why") or "").strip()[:600]
        if code in known_codes and why:
            because.append({"finding": code, "why": why})
    category = raw.get("category")
    confidence = raw.get("confidence")
    if confidence not in CONFIDENCE or not because:
        confidence = "low"
    return {
        "likely_cause": str(raw.get("likely_cause") or "").strip()[:1500],
        "category": category if category in CATEGORIES else "other",
        "confidence": confidence,
        "because": because[:8],
        "steps": _strings(raw.get("steps"), limit=10),
        "rule_out": _strings(raw.get("rule_out"), limit=6),
        "missing": _strings(raw.get("missing"), limit=6),
    }


def troubleshoot(settings: Settings, material: str, known_codes: set[str]) -> dict[str, Any]:
    raw = _ask(settings, material[:30000], TROUBLESHOOT_SHAPE)
    return clean_troubleshoot(raw, known_codes)
