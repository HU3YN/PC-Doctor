"""Signing in.

One master account owns everything stored here. Passwords are hashed with
scrypt (slow on purpose, salted per password). A signed-in browser holds a
random token in an HttpOnly cookie; the database keeps only the token's hash,
so a copy of the database cannot be used to sign in.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Account, LoginSession

COOKIE = "pcdoctor_session"
SESSION_DAYS = 30
MIN_PASSWORD_LENGTH = 10
_N, _R, _P = 2**14, 8, 1  # scrypt cost


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    encoded = [base64.b64encode(part).decode() for part in (salt, digest)]
    return "$".join(["scrypt", str(_N), str(_R), str(_P), *encoded])


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(
            password.encode(),
            salt=base64.b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def master_exists(db: Session) -> bool:
    return db.scalar(select(Account.id).limit(1)) is not None


def create_session(db: Session, account: Account) -> str:
    token = new_token()
    db.execute(delete(LoginSession).where(LoginSession.expires_at < utcnow()))
    db.add(
        LoginSession(
            token_hash=token_hash(token),
            account_id=account.id,
            expires_at=utcnow() + timedelta(days=SESSION_DAYS),
        )
    )
    db.commit()
    return token


def account_for(db: Session, token: str | None) -> Account | None:
    if not token:
        return None
    session = db.scalar(select(LoginSession).where(LoginSession.token_hash == token_hash(token)))
    if session is None or session.expires_at < utcnow():
        return None
    return session.account


def end_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(LoginSession).where(LoginSession.token_hash == token_hash(token)))
        db.commit()


def setup_code(data_dir: Path) -> str:
    """The one-time code needed to create the master account.

    Whoever creates the master account owns the server, so on a machine other
    people can reach, "first visitor wins" would be a hole. The code is written
    to a file only someone with access to the server can read.
    """
    path = data_dir / "setup-code.txt"
    if path.is_file():
        code = path.read_text(encoding="utf-8").strip()
        if code:
            return code
    code = secrets.token_hex(4)
    data_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(code + "\n", encoding="utf-8")
    return code


class RateLimiter:
    """Allow at most ``limit`` events per ``window`` seconds for each key (kept in memory)."""

    def __init__(self, limit: int, window: float) -> None:
        self.limit, self.window = limit, window
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        events = self._events[key]
        while events and now - events[0] > self.window:
            events.popleft()
        if len(events) >= self.limit:
            return False
        events.append(now)
        return True

    def reset(self) -> None:
        self._events.clear()


login_attempts = RateLimiter(limit=8, window=15 * 60)
guest_uploads = RateLimiter(limit=30, window=60 * 60)
