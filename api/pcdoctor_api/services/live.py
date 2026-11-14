"""Live sessions: frame times and sensor readings streamed while a capture runs.

The master opens a session and gets a token. The collector on the PC being
tested sends samples with that token, about once a second, as NDJSON lines:

    {"type": "frame", "t": 12.34, "ms": 7.1}
    {"type": "sensor", "t": 12.0, "values": {"cpu_temp_c": 71.5, "gpu_load_pct": 98}}
    {"type": "end"}

Like a photo link, the token can only add: it reads nothing back. Samples go
into a bounded buffer per session - the newest few thousand frames and the
newest few hundred sensor readings - which the master's Live page polls.
Nothing here is written to the database: a live view is for watching, and the
finished run is uploaded as usual.

With Redis configured (PCDOCTOR_REDIS_URL) the buffer lives there, so several
API copies see the same session. Otherwise it lives in this process.
"""

from __future__ import annotations

import json
import math
import re
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from . import auth

SESSION_HOURS = 6
MAX_SESSIONS = 20  # open at once; the oldest is dropped beyond this
MAX_FRAMES = 6000  # about a minute at 100 fps
MAX_SENSOR_ROWS = 600  # ten minutes at one reading a second
MAX_BATCH_BYTES = 512 * 1024
MAX_BATCH_LINES = 5000
MAX_SENSOR_VALUES = 32
_SENSOR_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


class SampleError(ValueError):
    """The batch as a whole cannot be used. The message is safe to show."""


@dataclass
class Batch:
    frames: list[tuple[float, float]] = field(default_factory=list)
    sensors: list[tuple[float, dict[str, float]]] = field(default_factory=list)
    ended: bool = False
    rejected: int = 0


def _finite(value: Any, low: float, high: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        return None
    return number


def parse_batch(body: bytes) -> Batch:
    """Read one NDJSON batch. A bad line is counted and skipped; only a batch
    that is too big or not text at all is refused as a whole."""
    if len(body) > MAX_BATCH_BYTES:
        raise SampleError("The batch is too large. Send at most 512 KB at a time.")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise SampleError("The batch must be UTF-8 text, one JSON object per line.") from None
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) > MAX_BATCH_LINES:
        raise SampleError("The batch has too many lines. Send at most 5000 at a time.")
    batch = Batch()
    for line in lines:
        try:
            item = json.loads(line)
        except (ValueError, RecursionError):
            batch.rejected += 1
            continue
        kind = item.get("type") if isinstance(item, dict) else None
        seconds = _finite(item.get("t"), 0, 24 * 3600) if isinstance(item, dict) else None
        if kind == "end":
            batch.ended = True
        elif kind == "frame" and seconds is not None:
            ms = _finite(item.get("ms"), 0.001, 3_600_000)
            if ms is None:
                batch.rejected += 1
            else:
                batch.frames.append((seconds, ms))
        elif kind == "sensor" and seconds is not None and isinstance(item.get("values"), dict):
            values = {}
            for name, value in list(item["values"].items())[:MAX_SENSOR_VALUES]:
                number = _finite(value, -1e6, 1e6)
                if isinstance(name, str) and _SENSOR_NAME.match(name) and number is not None:
                    values[name] = number
            if values:
                batch.sensors.append((seconds, values))
            else:
                batch.rejected += 1
        else:
            batch.rejected += 1
    return batch


@dataclass
class Session:
    id: str
    label: str
    created: float
    expires: float
    frames: deque = field(default_factory=lambda: deque(maxlen=MAX_FRAMES))
    sensors: deque = field(default_factory=lambda: deque(maxlen=MAX_SENSOR_ROWS))
    frames_total: int = 0
    sensor_rows_total: int = 0
    last_sample: float | None = None
    ended: bool = False

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "created_at": self.created,
            "expires_at": self.expires,
            "frames_total": self.frames_total,
            "sensor_rows_total": self.sensor_rows_total,
            "last_sample_at": self.last_sample,
            "ended": self.ended,
        }


class MemoryStore:
    """Sessions in this process. Right for one API process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}
        self._by_token: dict[str, str] = {}

    def _expire(self, now: float) -> None:
        for session_id in [s.id for s in self._sessions.values() if s.expires < now]:
            self._drop(session_id)

    def _drop(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        for token, owner in list(self._by_token.items()):
            if owner == session_id:
                del self._by_token[token]

    def create(self, label: str) -> tuple[Session, str]:
        now = time.time()
        token = auth.new_token()
        session = Session(
            id=secrets.token_hex(8), label=label, created=now, expires=now + SESSION_HOURS * 3600
        )
        with self._lock:
            self._expire(now)
            while len(self._sessions) >= MAX_SESSIONS:
                self._drop(min(self._sessions.values(), key=lambda s: s.created).id)
            self._sessions[session.id] = session
            self._by_token[auth.token_hash(token)] = session.id
        return session, token

    def add(self, token: str, batch: Batch) -> Session | None:
        now = time.time()
        with self._lock:
            self._expire(now)
            session = self._sessions.get(self._by_token.get(auth.token_hash(token), ""))
            if session is None:
                return None
            session.frames.extend(batch.frames)
            session.sensors.extend(batch.sensors)
            session.frames_total += len(batch.frames)
            session.sensor_rows_total += len(batch.sensors)
            if batch.frames or batch.sensors:
                session.last_sample = now
            session.ended = session.ended or batch.ended
            return session

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            self._expire(time.time())
            session = self._sessions.get(session_id)
            if session is None:
                return None
            # A copy, so the caller reads it without holding the lock.
            copy = Session(**{**session.__dict__})
            copy.frames, copy.sensors = deque(session.frames), deque(session.sensors)
            return copy

    def list(self) -> list[Session]:
        with self._lock:
            self._expire(time.time())
            return sorted(self._sessions.values(), key=lambda s: s.created, reverse=True)

    def delete(self, session_id: str) -> bool:
        with self._lock:
            found = session_id in self._sessions
            self._drop(session_id)
            return found


class RedisStore:
    """Sessions in Redis, shared by every API copy. Every key expires with the session."""

    PREFIX = "pcdoctor:live:"

    def __init__(self, client: Any) -> None:
        self.redis = client

    def _key(self, *parts: str) -> str:
        return self.PREFIX + ":".join(parts)

    def create(self, label: str) -> tuple[Session, str]:
        now = time.time()
        token = auth.new_token()
        session = Session(
            id=secrets.token_hex(8), label=label, created=now, expires=now + SESSION_HOURS * 3600
        )
        ttl = SESSION_HOURS * 3600
        meta = {"label": label, "created": now, "expires": session.expires}
        pipe = self.redis.pipeline()
        pipe.set(self._key("meta", session.id), json.dumps(meta), ex=ttl)
        pipe.set(self._key("token", auth.token_hash(token)), session.id, ex=ttl)
        pipe.zadd(self._key("index"), {session.id: now})
        pipe.execute()
        return session, token

    def _ttl(self, session_id: str) -> int:
        remaining = self.redis.ttl(self._key("meta", session_id))
        return int(remaining) if remaining and int(remaining) > 0 else 0

    def add(self, token: str, batch: Batch) -> Session | None:
        session_id = self.redis.get(self._key("token", auth.token_hash(token)))
        if session_id is None:
            return None
        session_id = session_id.decode() if isinstance(session_id, bytes) else session_id
        ttl = self._ttl(session_id)
        if not ttl:
            return None
        pipe = self.redis.pipeline()
        if batch.frames:
            frames_key = self._key("frames", session_id)
            pipe.rpush(frames_key, *[json.dumps(f) for f in batch.frames])
            pipe.ltrim(frames_key, -MAX_FRAMES, -1)
            pipe.expire(frames_key, ttl)
        if batch.sensors:
            sensors_key = self._key("sensors", session_id)
            pipe.rpush(sensors_key, *[json.dumps(s) for s in batch.sensors])
            pipe.ltrim(sensors_key, -MAX_SENSOR_ROWS, -1)
            pipe.expire(sensors_key, ttl)
        counts = self._key("counts", session_id)
        pipe.hincrby(counts, "frames", len(batch.frames))
        pipe.hincrby(counts, "sensors", len(batch.sensors))
        if batch.frames or batch.sensors:
            pipe.hset(counts, "last", time.time())
        if batch.ended:
            pipe.hset(counts, "ended", 1)
        pipe.expire(counts, ttl)
        pipe.execute()
        return self.get(session_id, with_samples=False)

    def get(self, session_id: str, with_samples: bool = True) -> Session | None:
        raw = self.redis.get(self._key("meta", session_id))
        if raw is None:
            return None
        meta = json.loads(raw)
        counts = {
            (k.decode() if isinstance(k, bytes) else k): v
            for k, v in (self.redis.hgetall(self._key("counts", session_id)) or {}).items()
        }
        session = Session(
            id=session_id, label=meta["label"], created=meta["created"], expires=meta["expires"]
        )
        session.frames_total = int(counts.get("frames", 0))
        session.sensor_rows_total = int(counts.get("sensors", 0))
        session.last_sample = float(counts["last"]) if "last" in counts else None
        session.ended = bool(int(counts.get("ended", 0)))
        if with_samples:
            for item in self.redis.lrange(self._key("frames", session_id), 0, -1):
                session.frames.append(tuple(json.loads(item)))
            for item in self.redis.lrange(self._key("sensors", session_id), 0, -1):
                seconds, values = json.loads(item)
                session.sensors.append((seconds, values))
        return session

    def list(self) -> list[Session]:
        found = []
        for raw_id in self.redis.zrevrange(self._key("index"), 0, MAX_SESSIONS * 5):
            session_id = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
            session = self.get(session_id, with_samples=False)
            if session is None:
                self.redis.zrem(self._key("index"), session_id)
            else:
                found.append(session)
        return found[:MAX_SESSIONS]

    def delete(self, session_id: str) -> bool:
        removed = self.redis.delete(
            self._key("meta", session_id),
            self._key("frames", session_id),
            self._key("sensors", session_id),
            self._key("counts", session_id),
        )
        self.redis.zrem(self._key("index"), session_id)
        # The token key expires by itself; without its meta it leads nowhere.
        return bool(removed)


store: MemoryStore | RedisStore = MemoryStore()
ingest_limit = auth.RateLimiter("live", limit=600, window=60)  # batches per token


def use_redis(redis_url: str) -> None:
    """Keep sessions, and the per-token batch count, in Redis when one is
    configured, so several API copies share them."""
    global store
    if not redis_url:
        store = MemoryStore()
        ingest_limit._redis = None
        return
    try:
        import redis

        client = redis.Redis.from_url(redis_url, socket_timeout=2)
    except ImportError:
        store = MemoryStore()
        ingest_limit._redis = None
        return
    store = RedisStore(client)
    ingest_limit._redis = client


def view(session: Session) -> dict[str, Any]:
    """What the Live page shows: the buffer plus a few figures worked out from it."""
    frames = list(session.frames)
    recent = [ms for t, ms in frames if frames and t >= frames[-1][0] - 10]
    stats: dict[str, Any] = {"frames_in_last_10_s": len(recent)}
    if recent:
        ordered = sorted(recent)
        stats["avg_fps_last_10_s"] = round(1000 * len(recent) / sum(recent), 1)
        slowest = ordered[-max(1, len(ordered) // 100) :]
        stats["one_pct_low_fps_last_10_s"] = round(1000 / (sum(slowest) / len(slowest)), 1)
        stats["worst_frame_ms_last_10_s"] = round(ordered[-1], 2)
    return {
        **session.summary(),
        "stats": stats,
        "frames": [{"t": t, "ms": ms} for t, ms in frames],
        "sensors": [{"t": t, "values": values} for t, values in session.sensors],
    }
