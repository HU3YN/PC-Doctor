"""Reference data: stop codes, the list of checks, form options, statistics, demo data."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pcdoctor_analysis import RULES_VERSION
from pcdoctor_analysis import __version__ as analysis_version
from pcdoctor_analysis.model import CATEGORIES
from pcdoctor_analysis.rules import all_rules
from pcdoctor_analysis.stopcodes import lookup, search
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import __version__
from ..config import Settings, get_settings
from ..db import get_db
from ..models import Finding, Run, WorkLogEntry
from ..schemas import DEVICE_TYPES, STATUSES, DemoResult, SimilarCase, WorkLogBrief
from ..services import demo as demo_service
from ..services.similarity import Query as SimilarityQuery
from ..services.similarity import find_similar

router = APIRouter(prefix="/api", tags=["reference"])

Db = Annotated[Session, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]


@router.get("/health")
def health(db: Db) -> dict[str, str]:
    db.execute(select(1))
    return {"status": "ok", "version": __version__, "rules_version": RULES_VERSION}


@router.get("/meta")
def meta() -> dict[str, Any]:
    """Everything the dashboard's forms and filters need to know."""
    return {
        "version": __version__,
        "analysis_version": analysis_version,
        "rules_version": RULES_VERSION,
        "categories": CATEGORIES,
        "statuses": STATUSES,
        "device_types": DEVICE_TYPES,
        "rules": [
            {
                "code": r.code,
                "category": r.category,
                "title": r.title,
                "detects": r.detects,
                "needs": r.needs,
            }
            for r in all_rules()
        ],
    }


@router.get("/stopcodes")
def stop_codes(
    q: Annotated[str, Query(max_length=100)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[dict[str, Any]]:
    return [entry.to_dict() for entry in search(q, limit)]


@router.get("/stopcodes/{code}")
def stop_code(code: str, db: Db) -> dict[str, Any]:
    """One stop code, with the work-log cases where it has been seen before."""
    entry = lookup(code)
    if entry is None:
        raise HTTPException(status_code=404, detail="Stop code not in the built-in list.")
    matches = find_similar(
        list(db.scalars(select(WorkLogEntry))), SimilarityQuery(codes=[entry.hex]), limit=10
    )
    return {
        **entry.to_dict(),
        "cases": [
            SimilarCase(
                entry=WorkLogBrief.model_validate(m.entry), score=m.score, reasons=m.reasons
            ).model_dump(mode="json")
            for m in matches
        ],
    }


@router.get("/stats")
def stats(db: Db, include_demo: bool = False) -> dict[str, Any]:
    """Counts for the overview page - and for tracking the project's numbers."""
    runs = list(
        db.scalars(select(Run) if include_demo else select(Run).where(Run.is_demo.is_(False)))
    )
    entries = list(
        db.scalars(
            select(WorkLogEntry)
            if include_demo
            else select(WorkLogEntry).where(WorkLogEntry.is_demo.is_(False))
        )
    )
    run_ids = [r.id for r in runs]
    found: Counter[str] = Counter()
    if run_ids:
        rows = db.execute(
            select(Finding.code, func.count())
            .where(Finding.run_id.in_(run_ids))
            .group_by(Finding.code)
        )
        found = Counter({code: count for code, count in rows})

    def week_start(run: Run) -> str:
        day = run.created_at.date()
        return (day - timedelta(days=day.weekday())).isoformat()

    return {
        "runs": len(runs),
        "runs_by_verdict": dict(Counter(r.verdict for r in runs)),
        "runs_by_week": dict(sorted(Counter(week_start(r) for r in runs).items())),
        "fault_types_detectable": len(all_rules()),
        "fault_types_seen": len(found),
        "findings_by_code": dict(found.most_common()),
        "work_log_entries": len(entries),
        "work_log_by_category": dict(Counter(e.category for e in entries).most_common()),
        "work_log_by_status": dict(Counter(e.status for e in entries)),
        "work_log_minutes": sum(e.minutes_spent or 0 for e in entries),
        "demo_runs": db.scalar(select(func.count()).select_from(Run).where(Run.is_demo)) or 0,
        "demo_work_log": db.scalar(
            select(func.count()).select_from(WorkLogEntry).where(WorkLogEntry.is_demo)
        )
        or 0,
    }


@router.post("/demo", response_model=DemoResult)
def load_demo(db: Db, settings: Config) -> DemoResult:
    runs, entries = demo_service.load_demo(db, settings)
    return DemoResult(runs=runs, work_log=entries)


@router.delete("/demo", response_model=DemoResult)
def clear_demo(db: Db, settings: Config) -> DemoResult:
    runs, entries = demo_service.clear_demo(db, settings)
    return DemoResult(runs=runs, work_log=entries)
