"""Runs: upload, list, read, re-analyse, delete."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse
from pcdoctor_analysis import RULES_VERSION
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from starlette.concurrency import run_in_threadpool

from ..config import Settings, get_settings
from ..db import get_db
from ..deps import ClientKey, Master, MaybeAccount, SignedIn
from ..models import Run, ShareKey, WorkLogEntry
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
from ..services import auth as auth_service
from ..services import ingest as ingest_service
from ..services import notify
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


def _check_upload_limit(request: Request, settings: Settings, key: str) -> None:
    """Rate-limit a guest upload. The Discord bot, which uploads for a whole
    server from one address, may send the bot token to use its own higher
    limit. The token only picks the limit: the upload is still a guest upload."""
    given = request.headers.get(auth_service.BOT_TOKEN_HEADER)
    if given is not None:
        if not auth_service.is_bot_token(settings.bot_token, given):
            raise HTTPException(status_code=401, detail="The bot token is not right.")
        if not auth_service.bot_uploads.allow("bot"):
            raise HTTPException(
                status_code=429, detail="Too many uploads from the bot. Try again in an hour."
            )
        return
    if not auth_service.guest_uploads.allow(key):
        raise HTTPException(
            status_code=429, detail="Too many uploads from here. Try again in an hour."
        )


@router.post("", response_model=RunUploaded, status_code=201)
async def upload_run(
    request: Request,
    response: Response,
    background: BackgroundTasks,
    db: Db,
    settings: Config,
    account: MaybeAccount,
    key: ClientKey,
    file: Annotated[
        UploadFile, File(description="The .zip from the collector, or a PresentMon .csv")
    ],
    label: Annotated[str, Form(max_length=200)] = "",
) -> RunUploaded:
    """Upload a run. Anyone may: a guest gets back a private key for that one
    run and can see nothing else; the master sees every run."""
    # Only the master's own uploads are "master" runs. Everyone else - no
    # account, or a member account - is limited and gets a private key.
    guest = account is None or account.role != "master"
    if guest:
        _check_upload_limit(request, settings, key)
    data = await read_limited(file, settings.max_upload_mb * 1024 * 1024)
    try:
        # Unpacking and analysing takes a while: on a thread, so other
        # requests are not held up behind it.
        result = await run_in_threadpool(
            ingest_service.ingest,
            db,
            settings,
            data,
            label=label,
            source="guest" if guest else "master",
        )
    except ingest_service.UploadError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    if not result.created:
        response.status_code = 200
    share_key = None
    summary = RunSummary.model_validate(result.run)
    if guest:
        # A fresh key for every upload; only its hash is kept. Earlier keys to
        # the same run keep working.
        share_key = auth_service.new_token()
        own_label = result.run.label if result.created else label.strip()[:200]
        add_share_key(db, result.run, auth_service.token_hash(share_key), own_label)
        if account is not None and result.created:
            result.run.owner_id = account.id
        db.commit()
        if result.created:
            background.add_task(notify.new_guest_run, settings, result.run)
        # Never echo a label someone else typed for the same file.
        summary = summary.model_copy(update={"label": own_label})
    return RunUploaded(run=summary, duplicate=not result.created, share_key=share_key)


def add_share_key(db: Session, run: Run, key_hash: str, label: str) -> None:
    db.add(ShareKey(run=run, key_hash=key_hash, label=label))


@router.get("", response_model=RunList)
def list_runs(
    db: Db,
    _: Master,
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
def read_run(run_id: str, db: Db, _: Master) -> RunDetail:
    return detail(db, get_run(db, run_id))


@router.get("/{run_id}/series")
def read_series(run_id: str, db: Db, _: Master) -> dict[str, Any]:
    """The chart data: frame times and sensor readings, already downsampled."""
    return (get_run(db, run_id).result or {}).get("series") or {}


@router.patch("/{run_id}", response_model=RunDetail)
def update_run(run_id: str, patch: RunPatch, db: Db, _: Master) -> RunDetail:
    run = get_run(db, run_id)
    if patch.label is not None:
        run.label = patch.label.strip()
    if patch.notes is not None:
        run.notes = patch.notes.strip()
    db.commit()
    return detail(db, run)


@router.post("/{run_id}/reanalyze", response_model=RunDetail)
def reanalyze_run(run_id: str, db: Db, settings: Config, _: Master) -> RunDetail:
    run = get_run(db, run_id)
    try:
        ingest_service.reanalyze(db, settings, run)
    except ingest_service.UploadError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    db.refresh(run)
    return detail(db, run)


@router.get("/{run_id}/download")
def download_run(run_id: str, db: Db, settings: Config, _: Master) -> FileResponse:
    run = get_run(db, run_id)
    path = settings.runs_dir / run.file_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The original upload is no longer on disk.")
    return FileResponse(
        path, media_type="application/zip", filename=f"pcdoctor-run-{run.id[:8]}.zip"
    )


@router.delete("/{run_id}", status_code=204)
def remove_run(run_id: str, db: Db, settings: Config, _: Master) -> None:
    ingest_service.delete_run(db, settings, get_run(db, run_id))


mine = APIRouter(prefix="/api/me", tags=["member"])


@mine.get("/runs", response_model=RunList)
def my_runs(db: Db, account: SignedIn) -> RunList:
    """The runs this account uploaded. Members see these and nothing else."""
    runs = list(
        db.scalars(
            select(Run).where(Run.owner_id == account.id).order_by(Run.created_at.desc()).limit(200)
        )
    )
    return RunList(items=[RunSummary.model_validate(r) for r in runs], total=len(runs))


def own_run(db: Session, run_id: str, account_id: int) -> Run:
    run = get_run(db, run_id)
    if run.owner_id != account_id:
        # The same answer as for a run that does not exist: do not confirm it does.
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


@mine.get("/runs/{run_id}", response_model=RunDetail)
def my_run(run_id: str, db: Db, account: SignedIn) -> RunDetail:
    full = detail(db, own_run(db, run_id, account.id))
    return full.model_copy(update={"similar_cases": [], "work_log": [], "notes": ""})


@mine.get("/runs/{run_id}/series")
def my_run_series(run_id: str, db: Db, account: SignedIn) -> dict[str, Any]:
    return (own_run(db, run_id, account.id).result or {}).get("series") or {}


@mine.delete("/runs/{run_id}", status_code=204)
def remove_my_run(run_id: str, db: Db, settings: Config, account: SignedIn) -> None:
    ingest_service.delete_run(db, settings, own_run(db, run_id, account.id))


shared = APIRouter(prefix="/api/shared", tags=["guest"])


def key_for(db: Session, key: str) -> ShareKey:
    found = db.scalar(
        select(ShareKey)
        .where(ShareKey.key_hash == auth_service.token_hash(key))
        .options(selectinload(ShareKey.run).selectinload(Run.findings))
    )
    if found is None:
        raise HTTPException(status_code=404, detail="This link is not valid (or no longer is).")
    return found


def run_for_key(db: Session, key: str) -> Run:
    return key_for(db, key).run


@shared.get("/{key}", response_model=RunDetail)
def read_shared_run(key: str, db: Db) -> RunDetail:
    """One run, for whoever holds its private key. Nothing from the work log
    and nothing about any other run is included, and the label is the one
    this key's uploader typed."""
    share = key_for(db, key)
    full = detail(db, share.run)
    return full.model_copy(
        update={"similar_cases": [], "work_log": [], "notes": "", "label": share.label}
    )


@shared.get("/{key}/series")
def read_shared_series(key: str, db: Db) -> dict[str, Any]:
    return (run_for_key(db, key).result or {}).get("series") or {}
