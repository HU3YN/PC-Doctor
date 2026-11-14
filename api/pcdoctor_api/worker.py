"""The analysis worker: takes jobs the upload service queued and does the
slow part (unpack, analyse, store).

    python -m pcdoctor_api.worker

Needs PCDOCTOR_REDIS_URL and the same database and data folder as the API.
Run as many copies as you like: each job is taken by exactly one of them.
"""

from __future__ import annotations

import hashlib
import json
import re
import signal
import time
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from . import metrics
from .config import Settings, get_settings
from .db import get_db, migrate, utcnow
from .services import ingest, notify

JOBS_KEY = "pcdoctor:jobs"
JOB_PREFIX = "pcdoctor:job:"
JOB_TTL_SECONDS = 24 * 3600
_SAFE_NAME = re.compile(r"[A-Za-z0-9_-]{8,64}\.zip")
_HASH = re.compile(r"[0-9a-f]{64}")


def process_job(db: Session, settings: Settings, job: dict[str, Any]) -> dict[str, str]:
    """Handle one job and return its final state. Never raises for a bad job:
    the queue is filled by another service, so its contents are checked too."""
    name = str(job.get("file") or "")
    share_hash = str(job.get("share_hash") or "")
    if not _SAFE_NAME.fullmatch(name) or not _HASH.fullmatch(share_hash):
        return {"status": "failed", "error": "The upload job was malformed."}
    path = settings.spool / name
    try:
        data = path.read_bytes()
    except OSError:
        return {"status": "failed", "error": "The uploaded file was no longer available."}
    try:
        if hashlib.sha256(data).hexdigest() != job.get("sha256"):
            return {"status": "failed", "error": "The uploaded file was damaged in storage."}
        result = ingest.ingest(
            db, settings, data, label=str(job.get("label") or "")[:200], source="guest"
        )
        # The uploader holds the key; only its hash ever reaches us.
        result.run.share_hash = share_hash
        db.commit()
        if result.created:
            notify.new_guest_run(settings, result.run)
    except ingest.UploadError as error:
        return {"status": "failed", "error": str(error)}
    finally:
        path.unlink(missing_ok=True)
    queued = job.get("queued_at")
    if isinstance(queued, str):
        try:
            waited = (
                utcnow() - datetime.fromisoformat(queued.replace("Z", "+00:00"))
            ).total_seconds()
            metrics.UPLOAD_TO_DIAGNOSIS.observe(max(0.0, waited))
        except ValueError:
            pass
    return {"status": "done", "run_id": result.run.id}


def handle(redis_client: Any, raw: bytes | str, settings: Settings) -> dict[str, str]:
    try:
        job = json.loads(raw)
        if not isinstance(job, dict):
            raise ValueError
    except ValueError:
        metrics.JOBS.labels("malformed").inc()
        return {"status": "failed", "error": "The upload job was malformed."}
    db = next(get_db())
    try:
        state = process_job(db, settings, job)
    except Exception as error:  # noqa: BLE001 - one bad job must not stop the worker
        db.rollback()
        print(f"worker: job failed unexpectedly: {error.__class__.__name__}: {error}", flush=True)
        state = {"status": "failed", "error": "The run could not be analysed."}
    finally:
        db.close()
    metrics.JOBS.labels(state["status"]).inc()
    job_id = str(job.get("id") or "")
    if re.fullmatch(r"[A-Za-z0-9_-]{8,64}", job_id):
        redis_client.set(JOB_PREFIX + job_id, json.dumps(state), ex=JOB_TTL_SECONDS)
    return state


def main() -> None:
    import redis
    from prometheus_client import start_http_server

    settings = get_settings()
    if not settings.redis_url:
        raise SystemExit("Set PCDOCTOR_REDIS_URL to run the worker.")
    settings.spool.mkdir(parents=True, exist_ok=True)
    if settings.auto_migrate:
        migrate()
    client = redis.Redis.from_url(settings.redis_url)
    start_http_server(9101)  # metrics, for Prometheus

    running = True

    def stop(*_: object) -> None:
        nonlocal running
        running = False  # finish the job in hand, then leave

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print("PC Doctor worker: waiting for jobs", flush=True)
    while running:
        try:
            item = client.blpop([JOBS_KEY], timeout=5)
            metrics.WORKER_UP.set_to_current_time()
        except redis.RedisError as error:
            print(
                f"worker: Redis is not reachable ({error.__class__.__name__}); retrying", flush=True
            )
            time.sleep(3)
            continue
        if item is not None:
            state = handle(client, item[1], settings)
            print(f"worker: job {state['status']}", flush=True)


if __name__ == "__main__":
    main()
