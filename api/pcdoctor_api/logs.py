"""Keep private links and tokens out of the access log.

A guest's private link (/r/<key>, /api/shared/<key>), a phone's photo link
(/snap/<token>, /api/photo-links/<token>) and a live session's samples
address (/api/live/<token>/samples) carry the secret in the path. Anyone who
can read the server's logs could otherwise open those runs. The same paths
are redacted in nginx's log (web/nginx.conf).
"""

from __future__ import annotations

import logging
import re

# (pattern, replacement): the secret part becomes a placeholder.
_SECRETS = [
    (re.compile(r"^(/api/shared/|/r/|/api/photo-links/|/snap/)[^/?#]+"), r"\1<key>"),
    (re.compile(r"^/api/live/[^/?#]+/samples"), "/api/live/<token>/samples"),
]


def redact(path: str) -> str:
    for pattern, replacement in _SECRETS:
        path = pattern.sub(replacement, path)
    return path


class RedactPaths(logging.Filter):
    """For uvicorn's access log, whose arguments are
    (client, method, path, http version, status)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            args = list(record.args)
            if isinstance(args[2], str):
                args[2] = redact(args[2])
                record.args = tuple(args)
        return True


def install() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactPaths) for f in logger.filters):
        logger.addFilter(RedactPaths())
