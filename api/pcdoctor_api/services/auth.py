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
    return db.scalar(select(Account.id).where(Account.role == "master").limit(1)) is not None


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
    code = secrets.token_hex(8)  # 64 bits, and tries are rate-limited
    data_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(code + "\n", encoding="utf-8")
    return code


class RateLimiter:
    """Allow at most ``limit`` events per ``window`` seconds for each key.

    Counts are kept in memory, which is right for one process. With several
    API copies behind a load balancer each would count separately, so when
    Redis is configured the counts live there instead (see use_shared_limits).
    """

    def __init__(self, name: str, limit: int, window: float) -> None:
        self.name, self.limit, self.window = name, limit, window
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._redis = None

    def allow(self, key: str) -> bool:
        if self._redis is not None:
            try:
                redis_key = f"pcdoctor:limit:{self.name}:{key}"
                count = self._redis.incr(redis_key)
                if count == 1:
                    self._redis.expire(redis_key, int(self.window))
                return count <= self.limit
            except Exception:  # noqa: BLE001 - Redis down: fall back to counting here
                pass
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


login_attempts = RateLimiter("login", limit=8, window=15 * 60)
guest_uploads = RateLimiter("uploads", limit=30, window=60 * 60)
# The Discord bot's uploads (with a valid bot token). The limit is set from
# PCDOCTOR_BOT_UPLOADS_PER_HOUR when the app starts.
bot_uploads = RateLimiter("bot-uploads", limit=300, window=60 * 60)
BOT_TOKEN_HEADER = "x-pcdoctor-bot-token"


def is_bot_token(expected: str, given: str | None) -> bool:
    """True when ``given`` is the configured bot token. Compared in constant time."""
    if not expected or not given:
        return False
    return hmac.compare_digest(expected.encode(), given.encode())


def use_shared_limits(redis_url: str) -> None:
    """Keep rate-limit counts in Redis when one is configured."""
    client = None
    if redis_url:
        try:
            import redis

            client = redis.Redis.from_url(redis_url, socket_timeout=2)
        except ImportError:
            print("PC Doctor: PCDOCTOR_REDIS_URL is set but the redis package is missing.")
    for limiter in (login_attempts, guest_uploads, bot_uploads):
        limiter._redis = client
