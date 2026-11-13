"""Prometheus metrics for the API and the worker.

Counts and timings only - never a label taken from user input (labels use the
route's pattern, such as /api/runs/{run_id}, not the address that was asked for).
"""

from __future__ import annotations

import hmac
import time

from fastapi import APIRouter, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from .config import get_settings

REQUESTS = Counter("pcdoctor_http_requests_total", "API requests.", ["method", "route", "status"])
LATENCY = Histogram("pcdoctor_http_request_seconds", "API request time.", ["method", "route"])
RUNS = Counter("pcdoctor_runs_ingested_total", "Runs analysed and stored.", ["source", "verdict"])
ANALYSIS = Histogram(
    "pcdoctor_analysis_seconds",
    "Time to unpack, analyse and store one run.",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
UPLOAD_TO_DIAGNOSIS = Histogram(
    "pcdoctor_upload_to_diagnosis_seconds",
    "From the upload service accepting a run to its diagnosis being stored.",
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 300),
)
JOBS = Counter("pcdoctor_jobs_total", "Queue jobs handled by the worker.", ["outcome"])
WORKER_UP = Gauge("pcdoctor_worker_last_poll_timestamp", "When the worker last asked for a job.")

router = APIRouter()


async def record_request(request: Request, call_next):  # noqa: ANN001, ANN201
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        route = getattr(request.scope.get("route"), "path", "") or "other"
        if route.startswith("/api/"):
            REQUESTS.labels(request.method, route, str(status)).inc()
            LATENCY.labels(request.method, route).observe(time.perf_counter() - started)


@router.get("/api/metrics", include_in_schema=False)
def metrics(request: Request) -> Response:
    """For Prometheus only: needs the metrics token, and does not exist without one."""
    token = get_settings().metrics_token
    if not token:
        raise HTTPException(status_code=404, detail="Not found.")
    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(given.encode(), token.encode()):
        raise HTTPException(status_code=401, detail="A metrics token is needed.")
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
