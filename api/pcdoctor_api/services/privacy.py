"""Spot text in a work-log entry that looks like customer data.

The work log is for what was wrong with a machine and how it was fixed. It
must never hold who owned it. This only warns - it cannot know for sure - so
the entry is still saved and the dashboard shows the warning next to it.
"""

from __future__ import annotations

import re

_CHECKS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
        "This looks like an email address.",
    ),
    (
        re.compile(r"(?<![\dA-Za-z])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)"),
        "This looks like a phone number.",
    ),
    (
        re.compile(
            r"\b(?:serial(?:\s*(?:number|no\.?|#))?|s/n|service\s*tag)\s*[:#]?\s*[A-Z0-9-]{5,}",
            re.I,
        ),
        "This looks like a serial number or service tag.",
    ),
    (
        re.compile(
            r"\b(?:[Cc]ustomer|[Cc]lient|[Oo]wner)(?:'s)?\s+name\b"
            r"|\b(?:Mr|Mrs|Ms|Miss)\.?\s+[A-Z][a-z]+"
        ),
        "This may name a customer.",
    ),
]


def privacy_warnings(*texts: str) -> list[str]:
    combined = "\n".join(t for t in texts if t)
    return [message for pattern, message in _CHECKS if pattern.search(combined)]
