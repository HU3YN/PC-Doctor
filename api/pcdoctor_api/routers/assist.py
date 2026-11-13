"""The AI helper's endpoints (master only, and only when a key is configured)."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import Settings, get_settings
from ..db import get_db
from ..deps import Master
from ..models import Photo, Run, WorkLogEntry
from ..services import ai as ai_service
from ..services.similarity import find_similar
from .runs import similarity_query_for

router = APIRouter(prefix="/api/assist", tags=["AI helper"])

Db = Annotated[Session, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]


class DraftRequest(BaseModel):
    run_id: str | None = None
    photo_id: str | None = None
    notes: str = Field(default="", max_length=8000)  # the technician's own rough notes


@router.get("")
def helper_status(settings: Config, _: Master) -> dict[str, Any]:
    return {"available": ai_service.available(settings), "model": settings.ai_model}


def material_for(db: Session, request: DraftRequest) -> str:
    """Everything the helper may use, as plain text. Nothing else is sent."""
    parts: list[str] = []
    if request.run_id:
        run = db.get(Run, request.run_id, options=[selectinload(Run.findings)])
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        cpu, gpu = run.cpu or "unknown CPU", run.gpu or "unknown GPU"
        parts.append(f"PC: {cpu}, {gpu}, {run.ram_gb or '?'} GB RAM")
        parts.append("Automatic diagnosis findings:")
        for finding in run.findings:
            codes = f" [{', '.join(finding.error_codes)}]" if finding.error_codes else ""
            head = f"- ({finding.severity}, {finding.category}) {finding.title}{codes}"
            parts.append(f"{head}: {finding.summary}")
    if request.photo_id:
        photo = db.get(Photo, request.photo_id)
        if photo is None:
            raise HTTPException(status_code=404, detail="Photo not found.")
        reading = photo.reading or {}
        codes = [f"{c['hex']} {c['name']}" for c in reading.get("stop_codes", [])]
        parts.append("From a photo of the PC or its screen:")
        if codes:
            parts.append("Stop codes read: " + ", ".join(codes))
        if reading.get("drivers"):
            parts.append("Driver named: " + ", ".join(reading["drivers"]))
        if photo.ai:
            parts.append("What the photo shows: " + str(photo.ai.get("summary", "")))
            parts.extend(f"- {item}" for item in photo.ai.get("observations", []))
        elif photo.text:
            parts.append("Text read from it: " + photo.text[:1500])
    if request.notes.strip():
        parts.append("The technician's own notes (the only source for cause and fix):")
        parts.append(request.notes.strip())
    if not parts:
        raise HTTPException(status_code=422, detail="Give the helper a run, a photo or some notes.")
    return "\n".join(parts)


@router.post("/draft")
def draft(request: DraftRequest, db: Db, settings: Config, _: Master) -> dict[str, Any]:
    """Draft a work-log entry. A draft only: the technician reviews and saves it."""
    material = material_for(db, request)
    try:
        return ai_service.draft_entry(settings, material)
    except ai_service.AiUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
    except ai_service.AiError as error:
        raise HTTPException(status_code=502, detail=str(error)) from None


class TroubleshootRequest(BaseModel):
    run_id: str
    question: str = Field(default="", max_length=2000)  # what the technician wants to know


def troubleshoot_material(
    findings: list[Any],
    device: dict[str, Any],
    checks: list[dict[str, Any]],
    frame_stats: dict[str, Any] | None,
    earlier_jobs: list[WorkLogEntry] | None = None,
    question: str = "",
) -> str:
    """What the troubleshooter is shown: the findings with their numbers, what
    could not be checked, and the technician's own matching jobs."""
    parts = ["PC: " + ", ".join(f"{k}={v}" for k, v in device.items() if v)]
    if frame_stats:
        keep = ("avg_fps", "fps_1pct_low", "spikes_per_min", "hitches", "duration_s")
        stats = {k: frame_stats[k] for k in keep if frame_stats.get(k) is not None}
        parts.append("Frame statistics: " + json.dumps(stats))
    parts.append("Findings (worst first):" if findings else "Findings: none.")
    for finding in findings:
        severity = getattr(finding.severity, "value", finding.severity)
        codes = f" codes={','.join(finding.error_codes)}" if finding.error_codes else ""
        parts.append(f"- [{finding.code}] ({severity}, {finding.category}) {finding.title}{codes}")
        parts.append(f"  {finding.summary}")
        if finding.evidence:
            parts.append("  numbers: " + json.dumps(finding.evidence, default=str)[:1200])
    unchecked = [c["title"] for c in checks if c.get("status") in ("no_data", "error")]
    if unchecked:
        parts.append("Could not be checked (no data): " + "; ".join(unchecked))
    if earlier_jobs:
        parts.append("The technician's earlier jobs that look similar:")
        for job in earlier_jobs:
            parts.append(
                f"- {job.title} | cause: {job.root_cause or 'not recorded'} "
                f"| fix: {job.fix or 'not recorded'}"
            )
    if question.strip():
        parts.append("The technician asks: " + question.strip())
    return "\n".join(parts)


@router.post("/troubleshoot")
def troubleshoot(
    request: TroubleshootRequest, db: Db, settings: Config, _: Master
) -> dict[str, Any]:
    """The most likely root cause of a run and how to confirm it. Advice to
    check, not a verdict: it may only cite findings the run really has."""
    run = db.get(Run, request.run_id, options=[selectinload(Run.findings)])
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    result = run.result or {}
    query = similarity_query_for(run)
    earlier: list[WorkLogEntry] = []
    if query.codes or query.categories:
        matches = find_similar(list(db.scalars(select(WorkLogEntry))), query, limit=3)
        earlier = [m.entry for m in matches]
    material = troubleshoot_material(
        list(run.findings),
        result.get("device") or {},
        result.get("checks") or [],
        result.get("frame_stats"),
        earlier,
        request.question,
    )
    try:
        return ai_service.troubleshoot(settings, material, {f.code for f in run.findings})
    except ai_service.AiUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
    except ai_service.AiError as error:
        raise HTTPException(status_code=502, detail=str(error)) from None
