"""Runs: upload, list, read, re-analyse, delete."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from pcdoctor_analysis import RULES_VERSION
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..config import Settings, get_settings
from ..db import get_db
from ..models import Run, WorkLogEntry
from ..schemas import (
    FindingOut,
    RunDetail,
    RunList,
    RunPatch,
    RunSummary,
    RunUploaded,
    SimilarCase,
    WorkLogBrief,
)
from ..services import ingest as ingest_service
from ..services.similarity import Query as SimilarityQuery
from ..services.similarity import find_similar

router = APIRouter(prefix="/api/runs", tags=["runs"])

Db = Annotated[Session, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]


def get_run(db: Session, run_id: str) -> Run:
    run = db.get(Run, run_id, options=[selectinload(Run.findings)])
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


async def read_limited(upload: UploadFile, limit_bytes: int) -> bytes:
    """Read an upload without ever holding more than the limit in memory."""
    chunks: list[bytes] = []
    size = 0
    while chunk := await upload.read(1024 * 1024):
        size += len(chunk)
        if size > limit_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"The file is larger than the {limit_bytes // (1024 * 1024)} MB limit.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def similarity_query_for(run: Run) -> SimilarityQuery:
    """What to look for in the work log, given what this run found."""
    problems = [f for f in run.findings if f.severity in ("critical", "warning")]
    codes: list[str] = []
    for finding in problems:
        codes.extend(finding.error_codes or [])
    # Codes, fault kinds and parts only: the wording of a finding's title is
    # ours, not the technician's, so matching on it would be noise.
    return SimilarityQuery(
        codes=codes,
        categories=sorted({f.category for f in problems}),
        parts=[p for p in (run.cpu, run.gpu) if p],
    )


def detail(db: Session, run: Run) -> RunDetail:
    result: dict[str, Any] = run.result or {}
    series = result.get("series") or {}
    similar: list[SimilarCase] = []
    query = similarity_query_for(run)
    if query.codes or query.categories:
        entries = list(db.scalars(select(WorkLogEntry)))
        linked = {e.id for e in entries if e.run_id == run.id}
        matches = find_similar([e for e in entries if e.id not in linked], query, limit=5)
        similar = [
            SimilarCase(
                entry=WorkLogBrief.model_validate(m.entry), score=m.score, reasons=m.reasons
            )
            for m in matches
        ]
    logged = db.scalars(
        select(WorkLogEntry)
        .where(WorkLogEntry.run_id == run.id)
        .order_by(WorkLogEntry.occurred_on.desc(), WorkLogEntry.id.desc())
    )
    return RunDetail(
        **RunSummary.model_validate(run).model_dump(),
        notes=run.notes,
        collector_version=run.collector_version,
        file_bytes=run.file_bytes,
        rules_outdated=run.rules_version != RULES_VERSION,
        findings=[FindingOut.model_validate(f) for f in run.findings],
        checks=result.get("checks") or [],
        device=result.get("device") or {},
        frame_stats=result.get("frame_stats"),
        sensor_stats=result.get("sensor_stats") or {},
        analysis_notes=result.get("notes") or [],
        has_frames=bool((series.get("frames") or {}).get("t")),
        has_sensors=bool((series.get("sensors") or {}).get("t")),
        similar_cases=similar,
        work_log=[WorkLogBrief.model_validate(e) for e in logged],
    )


@router.post("", response_model=RunUploaded, status_code=201)
async def upload_run(
    response: Response,
    db: Db,
    settings: Config,
    file: Annotated[
        UploadFile, File(description="The .zip from the collector, or a PresentMon .csv")
    ],
    label: Annotated[str, Form(max_length=200)] = "",
) -> RunUploaded:
    data = await read_limited(file, settings.max_upload_mb * 1024 * 1024)
    try:
        result = ingest_service.ingest(db, settings, data, label=label)
    except ingest_service.UploadError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    if not result.created:
        response.status_code = 200
    return RunUploaded(run=RunSummary.model_validate(result.run), duplicate=not result.created)


@router.get("", response_model=RunList)
def list_runs(
    db: Db,
    verdict: Annotated[str | None, Query(pattern="^(critical|warning|ok)$")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RunList:
    query = select(Run)
    count = select(func.count()).select_from(Run)
    if verdict:
        query = query.where(Run.verdict == verdict)
        count = count.where(Run.verdict == verdict)
    runs = db.scalars(query.order_by(Run.created_at.desc()).limit(limit).offset(offset))
    return RunList(items=[RunSummary.model_validate(r) for r in runs], total=db.scalar(count) or 0)


@router.get("/{run_id}", response_model=RunDetail)
def read_run(run_id: str, db: Db) -> RunDetail:
    return detail(db, get_run(db, run_id))


@router.get("/{run_id}/series")
def read_series(run_id: str, db: Db) -> dict[str, Any]:
    """The chart data: frame times and sensor readings, already downsampled."""
    return (get_run(db, run_id).result or {}).get("series") or {}


@router.patch("/{run_id}", response_model=RunDetail)
def update_run(run_id: str, patch: RunPatch, db: Db) -> RunDetail:
    run = get_run(db, run_id)
    if patch.label is not None:
        run.label = patch.label.strip()
    if patch.notes is not None:
        run.notes = patch.notes.strip()
    db.commit()
    return detail(db, run)


@router.post("/{run_id}/reanalyze", response_model=RunDetail)
def reanalyze_run(run_id: str, db: Db, settings: Config) -> RunDetail:
    run = get_run(db, run_id)
    try:
        ingest_service.reanalyze(db, settings, run)
    except ingest_service.UploadError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    db.refresh(run)
    return detail(db, run)


@router.get("/{run_id}/download")
def download_run(run_id: str, db: Db, settings: Config) -> FileResponse:
    run = get_run(db, run_id)
    path = settings.runs_dir / run.file_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The original upload is no longer on disk.")
    return FileResponse(
        path, media_type="application/zip", filename=f"pcdoctor-run-{run.id[:8]}.zip"
    )


@router.delete("/{run_id}", status_code=204)
def remove_run(run_id: str, db: Db, settings: Config) -> None:
    ingest_service.delete_run(db, settings, get_run(db, run_id))
