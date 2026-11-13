"""Phase 3: the queue worker, metrics, and shared rate limits."""

from __future__ import annotations

import hashlib
import json

from pcdoctor_analysis import synth

from pcdoctor_api import metrics
from pcdoctor_api.config import get_settings
from pcdoctor_api.db import get_db
from pcdoctor_api.services import auth
from pcdoctor_api.worker import JOB_PREFIX, handle, process_job


def queue_job(name: str = "healthy", **overrides) -> dict:
    """Do what the Go upload service does: store the file, describe the job."""
    settings = get_settings()
    settings.spool.mkdir(parents=True, exist_ok=True)
    data = synth.build(name).zip_bytes()
    (settings.spool / "job-0001.zip").write_bytes(data)
    return {
        "id": "job-0001",
        "file": "job-0001.zip",
        "label": "bench 3",
        "share_hash": auth.token_hash("the-private-key"),
        "sha256": hashlib.sha256(data).hexdigest(),
        "queued_at": "2026-11-13T10:00:00Z",
        **overrides,
    }


def test_worker_stores_the_run_and_the_uploader_can_open_it(client, guest):
    job = queue_job("cpu_overheat")
    db = next(get_db())
    state = process_job(db, get_settings(), job)
    assert state["status"] == "done"
    assert not (get_settings().spool / job["file"]).exists()  # the spool is emptied
    shared = guest.get("/api/shared/the-private-key")
    assert shared.status_code == 200 and shared.json()["id"] == state["run_id"]
    listed = client.get("/api/runs").json()["items"]
    assert listed[0]["label"] == "bench 3" and listed[0]["verdict"] != "ok"


def test_worker_refuses_jobs_that_do_not_add_up(client):
    db = next(get_db())
    settings = get_settings()
    assert process_job(db, settings, queue_job(sha256="0" * 64))["error"].startswith(
        "The uploaded file was damaged"
    )
    assert process_job(db, settings, queue_job(file="../../etc/passwd"))["status"] == "failed"
    assert process_job(db, settings, queue_job(share_hash="short"))["status"] == "failed"
    assert (
        process_job(db, settings, {"file": "missing-file.zip", "share_hash": "a" * 64})["status"]
        == "failed"
    )
    job = queue_job()
    (settings.spool / job["file"]).write_bytes(b"not a run")
    job["sha256"] = hashlib.sha256(b"not a run").hexdigest()
    assert "not a PC Doctor run" in process_job(db, settings, job)["error"]
    assert client.get("/api/runs").json()["total"] == 0


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int | str] = {}

    def set(self, key, value, ex=None):  # noqa: ANN001
        self.values[key] = value

    def incr(self, key):  # noqa: ANN001
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    def expire(self, key, seconds):  # noqa: ANN001
        pass


def test_worker_records_the_job_state_for_the_uploader(client):
    redis = FakeRedis()
    state = handle(redis, json.dumps(queue_job()), get_settings())
    assert json.loads(redis.values[JOB_PREFIX + "job-0001"]) == state and state["status"] == "done"
    assert handle(redis, b"not json", get_settings())["status"] == "failed"


def test_metrics_need_the_token_and_do_not_exist_without_one(client, guest, monkeypatch):
    assert guest.get("/api/metrics").status_code == 404
    monkeypatch.setenv("PCDOCTOR_METRICS_TOKEN", "scrape-me")
    get_settings.cache_clear()
    assert guest.get("/api/metrics").status_code == 401
    assert client.get("/api/metrics").status_code == 401  # even the master: token only
    client.get("/api/runs/some-private-id")
    body = guest.get("/api/metrics", headers={"Authorization": "Bearer scrape-me"}).text
    assert "pcdoctor_http_requests_total" in body
    assert 'route="/api/runs/{run_id}"' in body and "some-private-id" not in body


def test_rate_limits_can_be_shared_through_redis(client, monkeypatch):
    limiter = auth.RateLimiter("test", limit=2, window=60)
    limiter._redis = FakeRedis()
    assert [limiter.allow("1.2.3.4") for _ in range(3)] == [True, True, False]
    assert limiter.allow("5.6.7.8")

    class Broken:
        def incr(self, key):  # noqa: ANN001
            raise ConnectionError

    limiter._redis = Broken()  # Redis down: keep limiting, in memory
    assert [limiter.allow("9.9.9.9") for _ in range(3)] == [True, True, False]
    _ = metrics
