"""The AI helper's endpoints (master only, and only when a key is configured)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, selectinload

from ..config import Settings, get_settings
from ..db import get_db
from ..deps import Master
from ..models import Photo, Run
from ..services import ai as ai_service

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
        parts.append(
            f"PC: {run.cpu or 'unknown CPU'}, {run.gpu or 'unknown GPU'}, {run.ram_gb or '?'} GB RAM"
        )
        parts.append("Automatic diagnosis findings:")
        for finding in run.findings:
            codes = f" [{', '.join(finding.error_codes)}]" if finding.error_codes else ""
            parts.append(
                f"- ({finding.severity}, {finding.category}) {finding.title}{codes}: {finding.summary}"
            )
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
