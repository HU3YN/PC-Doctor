"""Live view of a capture while it runs (see services/live.py)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..deps import Master
from ..services import live

router = APIRouter(prefix="/api/live", tags=["live"])


class NewSession(BaseModel):
    label: str = Field(default="", max_length=200)


@router.post("", status_code=201)
def open_session(body: NewSession, _: Master) -> dict[str, Any]:
    """Start a live session. The token is shown once; only its hash is kept."""
    session, token = live.store.create(body.label.strip())
    return {
        **session.summary(),
        "token": token,
        "samples_path": f"/api/live/{token}/samples",
    }


@router.get("")
def list_sessions(_: Master) -> list[dict[str, Any]]:
    return [session.summary() for session in live.store.list()]


@router.get("/{session_id}")
def read_session(session_id: str, _: Master) -> dict[str, Any]:
    session = live.store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="That live session has ended or expired.")
    return live.view(session)


@router.delete("/{session_id}", status_code=204)
def close_session(session_id: str, _: Master) -> None:
    if not live.store.delete(session_id):
        raise HTTPException(status_code=404, detail="That live session has ended or expired.")


@router.post("/{token}/samples")
async def add_samples(token: str, request: Request) -> dict[str, Any]:
    """Add samples to a live session. The token can add, and read nothing back:
    the answer only says how many lines were taken."""
    if not live.ingest_limit.allow(token[:64]):
        raise HTTPException(status_code=429, detail="Too many batches. Send about one a second.")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > live.MAX_BATCH_BYTES:
        raise HTTPException(status_code=413, detail="The batch is too large.")
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > live.MAX_BATCH_BYTES:
            raise HTTPException(status_code=413, detail="The batch is too large.")
    try:
        batch = live.parse_batch(bytes(body))
    except live.SampleError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    session = await run_in_threadpool(live.store.add, token, batch)
    if session is None:
        # The same answer for a wrong token and an expired one.
        raise HTTPException(
            status_code=404, detail="This live link is not valid (or no longer is)."
        )
    return {
        "accepted": len(batch.frames) + len(batch.sensors),
        "rejected": batch.rejected,
        "ended": session.ended,
    }
