"""Live sessions: the master opens one, a token adds samples, the master watches."""

from __future__ import annotations

import json

import pytest

from pcdoctor_api.services import live


def ndjson(*items: dict) -> bytes:
    return "\n".join(json.dumps(item) for item in items).encode()


def open_session(client, label: str = "bench 2") -> dict:
    created = client.post("/api/live", json={"label": label})
    assert created.status_code == 201, created.text
    return created.json()


def test_a_token_adds_samples_and_the_master_sees_them(client, guest):
    session = open_session(client)
    assert session["samples_path"] == f"/api/live/{session['token']}/samples"
    frames = [{"type": "frame", "t": i / 100, "ms": 10.0} for i in range(300)]
    frames[150]["ms"] = 80.0  # one hitch
    sensor = {"type": "sensor", "t": 1.0, "values": {"cpu_temp_c": 71.5, "gpu_load_pct": 98}}
    sent = guest.post(session["samples_path"], content=ndjson(*frames, sensor))
    assert sent.status_code == 200
    assert sent.json() == {"accepted": 301, "rejected": 0, "ended": False}

    seen = client.get(f"/api/live/{session['id']}").json()
    assert seen["label"] == "bench 2" and seen["frames_total"] == 300
    assert seen["sensors"] == [{"t": 1.0, "values": {"cpu_temp_c": 71.5, "gpu_load_pct": 98.0}}]
    assert seen["stats"]["worst_frame_ms_last_10_s"] == 80.0
    assert 90 < seen["stats"]["avg_fps_last_10_s"] < 100
    assert "token" not in seen  # the token is shown once, when the session opens

    ended = guest.post(session["samples_path"], content=ndjson({"type": "end"}))
    assert ended.json()["ended"] is True
    assert client.get("/api/live").json()[0]["ended"] is True


def test_the_token_reads_nothing_and_a_wrong_token_is_refused(client, guest):
    session = open_session(client)
    assert guest.get(f"/api/live/{session['id']}").status_code == 401
    assert guest.get(session["samples_path"]).status_code == 405  # no way to read through it
    wrong = guest.post("/api/live/not-the-token/samples", content=ndjson({"type": "end"}))
    assert wrong.status_code == 404


def test_bad_lines_are_counted_not_stored(client, guest):
    session = open_session(client)
    body = b"\n".join(
        [
            b"not json",
            json.dumps({"type": "frame", "t": 1, "ms": float("inf")}).encode(),  # Infinity
            json.dumps({"type": "frame", "t": 1, "ms": -5}).encode(),
            json.dumps({"type": "frame", "t": 1}).encode(),
            json.dumps({"type": "sensor", "t": 1, "values": {"Bad Name": 1, "x" * 50: 2}}).encode(),
            json.dumps({"type": "sensor", "t": 1, "values": {"cpu_temp_c": True}}).encode(),
            json.dumps({"type": "who knows"}).encode(),
            json.dumps([1, 2, 3]).encode(),
            json.dumps({"type": "frame", "t": 2, "ms": 16.6}).encode(),
        ]
    )
    answer = guest.post(session["samples_path"], content=body).json()
    assert answer == {"accepted": 1, "rejected": 8, "ended": False}
    assert client.get(f"/api/live/{session['id']}").json()["frames"] == [{"t": 2.0, "ms": 16.6}]


def test_batches_and_buffers_are_bounded(client, guest, monkeypatch):
    session = open_session(client)
    too_big = b"x" * (live.MAX_BATCH_BYTES + 1)
    assert guest.post(session["samples_path"], content=too_big).status_code == 413
    too_many = ndjson(*[{"type": "end"}] * (live.MAX_BATCH_LINES + 1))
    assert guest.post(session["samples_path"], content=too_many).status_code == 400
    assert guest.post(session["samples_path"], content=b"\xff\xfe").status_code == 400

    monkeypatch.setattr(live, "MAX_FRAMES", 50)
    small = open_session(client, "small buffer")
    frames = [{"type": "frame", "t": i, "ms": 5} for i in range(120)]
    guest.post(small["samples_path"], content=ndjson(*frames))
    seen = client.get(f"/api/live/{small['id']}").json()
    assert seen["frames_total"] == 120 and len(seen["frames"]) == 50
    assert seen["frames"][0]["t"] == 70  # the newest are kept


def test_batches_per_token_are_rate_limited(client, guest, monkeypatch):
    monkeypatch.setattr(live.ingest_limit, "limit", 2)
    session = open_session(client)
    end = ndjson({"type": "end"})
    assert [guest.post(session["samples_path"], content=end).status_code for _ in range(3)] == [
        200,
        200,
        429,
    ]


def test_closing_a_session_stops_its_token(client, guest):
    session = open_session(client)
    assert client.delete(f"/api/live/{session['id']}").status_code == 204
    assert guest.post(session["samples_path"], content=ndjson({"type": "end"})).status_code == 404
    assert client.get(f"/api/live/{session['id']}").status_code == 404


def test_only_the_newest_sessions_are_kept(client, monkeypatch):
    monkeypatch.setattr(live, "MAX_SESSIONS", 3)
    ids = [open_session(client, f"s{i}")["id"] for i in range(5)]
    listed = [s["id"] for s in client.get("/api/live").json()]
    assert listed == ids[:1:-1]


redis = pytest.importorskip("redis")


class FakeRedis:
    """Just enough of Redis for the live store, in memory."""

    def __init__(self) -> None:
        self.data: dict = {}

    def pipeline(self):
        return self

    def execute(self):
        return []

    def set(self, key, value, ex=None):  # noqa: ANN001
        self.data[key] = value.encode() if isinstance(value, str) else value

    def get(self, key):  # noqa: ANN001
        return self.data.get(key)

    def ttl(self, key):  # noqa: ANN001
        return 3600 if key in self.data else -2

    def expire(self, key, seconds):  # noqa: ANN001
        return True

    def zadd(self, key, mapping):  # noqa: ANN001
        self.data.setdefault(key, {}).update(mapping)

    def zrevrange(self, key, start, stop):  # noqa: ANN001
        items = sorted(self.data.get(key, {}).items(), key=lambda kv: kv[1], reverse=True)
        return [k.encode() for k, _ in items][start : stop + 1]

    def zrem(self, key, member):  # noqa: ANN001
        self.data.get(key, {}).pop(member, None)

    def rpush(self, key, *values):  # noqa: ANN001
        self.data.setdefault(key, []).extend(v.encode() for v in values)

    def ltrim(self, key, start, stop):  # noqa: ANN001
        items = self.data.get(key, [])
        self.data[key] = items[start:] if stop == -1 else items[start : stop + 1]

    def lrange(self, key, start, stop):  # noqa: ANN001
        items = self.data.get(key, [])
        return items[start:] if stop == -1 else items[start : stop + 1]

    def hincrby(self, key, field, amount):  # noqa: ANN001
        bucket = self.data.setdefault(key, {})
        bucket[field.encode()] = str(int(bucket.get(field.encode(), b"0")) + amount).encode()

    def hset(self, key, field, value):  # noqa: ANN001
        self.data.setdefault(key, {})[field.encode()] = str(value).encode()

    def hgetall(self, key):  # noqa: ANN001
        return self.data.get(key, {})

    def delete(self, *keys):  # noqa: ANN001
        return sum(self.data.pop(key, None) is not None for key in keys)


def test_the_redis_store_keeps_and_trims_samples(client, guest, monkeypatch):
    live.store = live.RedisStore(FakeRedis())
    monkeypatch.setattr(live, "MAX_FRAMES", 10)
    session = open_session(client)
    frames = [{"type": "frame", "t": i, "ms": 8} for i in range(25)]
    sensor = {"type": "sensor", "t": 3, "values": {"gpu_temp_c": 66}}
    guest.post(session["samples_path"], content=ndjson(*frames, sensor, {"type": "end"}))
    seen = client.get(f"/api/live/{session['id']}").json()
    assert seen["frames_total"] == 25 and len(seen["frames"]) == 10 and seen["ended"]
    assert seen["sensors"] == [{"t": 3, "values": {"gpu_temp_c": 66}}]
    assert [s["id"] for s in client.get("/api/live").json()] == [session["id"]]
    assert client.delete(f"/api/live/{session['id']}").status_code == 204
    assert client.get(f"/api/live/{session['id']}").status_code == 404


def test_with_redis_the_batch_limit_is_shared_too(monkeypatch):
    import sys
    import types

    client = object()
    fake = types.SimpleNamespace(Redis=types.SimpleNamespace(from_url=lambda url, **_: client))
    monkeypatch.setitem(sys.modules, "redis", fake)
    try:
        live.use_redis("redis://:secret@redis:6379/0")
        assert isinstance(live.store, live.RedisStore) and live.ingest_limit._redis is client
    finally:
        live.use_redis("")
    assert isinstance(live.store, live.MemoryStore) and live.ingest_limit._redis is None
