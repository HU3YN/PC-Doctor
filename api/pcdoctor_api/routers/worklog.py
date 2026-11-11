"""The work log: what was wrong, what was checked, what fixed it."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pcdoctor_analysis.model import CATEGORIES
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Run, WorkLogEntry
from ..schemas import (
    ImportResult,
    SimilarCase,
    SimilarQuery,
    WorkLogBrief,
    WorkLogCreate,
    WorkLogList,
    WorkLogOut,
    WorkLogUpdate,
)
from ..services import export as export_service
from ..services.privacy import privacy_warnings
from ..services.similarity import Query as SimilarityQuery
from ..services.similarity import code_key, find_similar, tokenize

router = APIRouter(prefix="/api/worklog", tags=["work log"])

Db = Annotated[Session, Depends(get_db)]


def get_entry(db: Session, entry_id: int) -> WorkLogEntry:
    entry = db.get(WorkLogEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Work-log entry not found.")
    return entry


def out(entry: WorkLogEntry) -> WorkLogOut:
    data = WorkLogOut.model_validate(entry)
    data.run_label = (entry.run.label or entry.run.headline) if entry.run else None
    data.privacy_warnings = privacy_warnings(
        entry.title,
        entry.device,
        entry.symptoms,
        entry.steps,
        entry.root_cause,
        entry.fix,
        entry.reference,
    )
    return data


def apply(db: Session, entry: WorkLogEntry, fields: WorkLogCreate | WorkLogUpdate) -> None:
    if fields.run_id and db.get(Run, fields.run_id) is None:
        raise HTTPException(status_code=422, detail="The linked run does not exist.")
    data = fields.model_dump()
    data["occurred_on"] = data["occurred_on"] or date.today()
    for name, value in data.items():
        setattr(entry, name, value)


def searchable_text(entry: WorkLogEntry) -> str:
    return " ".join(
        [
            entry.title,
            entry.device,
            entry.symptoms,
            entry.steps,
            entry.root_cause,
            entry.fix,
            entry.reference,
            " ".join(entry.components or []),
            " ".join(entry.error_codes or []),
            CATEGORIES.get(entry.category, ""),
        ]
    ).lower()


@router.get("", response_model=WorkLogList)
def list_entries(
    db: Db,
    q: Annotated[str, Query(max_length=200, description="Words that must all appear")] = "",
    category: str | None = None,
    status: str | None = None,
    device_type: str | None = None,
    code: Annotated[
        str | None, Query(max_length=40, description="An error code, e.g. 0x124")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> WorkLogList:
    query = select(WorkLogEntry)
    if category:
        query = query.where(WorkLogEntry.category == category)
    if status:
        query = query.where(WorkLogEntry.status == status)
    if device_type:
        query = query.where(WorkLogEntry.device_type == device_type)
    entries = list(
        db.scalars(query.order_by(WorkLogEntry.occurred_on.desc(), WorkLogEntry.id.desc()))
    )
    if code:
        wanted = code_key(code)
        entries = [e for e in entries if wanted in {code_key(c) for c in e.error_codes or []}]
    words = [w for w in q.lower().split() if w]
    if words:
        # Every word must appear somewhere in the entry. Word stems are tried
        # too, so "fans" finds an entry that says "fan".
        def matches(entry: WorkLogEntry) -> bool:
            text = searchable_text(entry)
            return all(w in text or any(t in text for t in tokenize(w)) for w in words)

        entries = [e for e in entries if matches(e)]
    return WorkLogList(items=[out(e) for e in entries[offset : offset + limit]], total=len(entries))


@router.post("", response_model=WorkLogOut, status_code=201)
def create_entry(fields: WorkLogCreate, db: Db) -> WorkLogOut:
    entry = WorkLogEntry()
    apply(db, entry, fields)
    db.add(entry)
    db.commit()
    return out(entry)


@router.post("/similar", response_model=list[SimilarCase])
def similar_entries(query: SimilarQuery, db: Db) -> list[SimilarCase]:
    """Earlier entries that look like this problem, with the reasons they match."""
    entries = list(db.scalars(select(WorkLogEntry)))
    matches = find_similar(
        entries,
        SimilarityQuery(
            text=query.text,
            codes=query.codes,
            categories=[query.category] if query.category else [],
            parts=query.parts,
        ),
        limit=query.limit,
        exclude_id=query.exclude_id,
    )
    return [
        SimilarCase(entry=WorkLogBrief.model_validate(m.entry), score=m.score, reasons=m.reasons)
        for m in matches
    ]


@router.get("/export")
def export_entries(
    db: Db,
    format: Annotated[str, Query(pattern="^(json|csv|md)$")] = "json",
    include_demo: bool = False,
) -> Any:
    query = select(WorkLogEntry).order_by(WorkLogEntry.occurred_on.desc(), WorkLogEntry.id.desc())
    if not include_demo:
        query = query.where(WorkLogEntry.is_demo.is_(False))
    entries = list(db.scalars(query))
    stamp = date.today().isoformat()
    if format == "csv":
        return PlainTextResponse(
            export_service.to_csv(entries),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="pcdoctor-worklog-{stamp}.csv"'},
        )
    if format == "md":
        return PlainTextResponse(
            export_service.to_markdown(entries),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="pcdoctor-worklog-{stamp}.md"'},
        )
    return export_service.to_json(entries)


@router.post("/import", response_model=ImportResult)
def import_entries(document: dict[str, Any], db: Db) -> ImportResult:
    """Load entries from a JSON export. Entries already in the log are skipped."""
    if document.get("format") != "pcdoctor-worklog" or not isinstance(
        document.get("entries"), list
    ):
        raise HTTPException(status_code=400, detail="This is not a PC Doctor work-log export.")
    existing = {(e.occurred_on, e.title, e.symptoms) for e in db.scalars(select(WorkLogEntry))}
    imported = skipped = 0
    for number, raw in enumerate(document["entries"], 1):
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail=f"Entry {number} is not an object.")
        try:
            fields = WorkLogCreate.model_validate({**raw, "run_id": None})
        except ValidationError as error:
            message = error.errors()[0]
            where = ".".join(str(part) for part in message["loc"])
            raise HTTPException(
                status_code=400,
                detail=f"Entry {number}: {where}: {message['msg']}",
            ) from None
        key = (fields.occurred_on or date.today(), fields.title, fields.symptoms)
        if key in existing:
            skipped += 1
            continue
        entry = WorkLogEntry()
        apply(db, entry, fields)
        db.add(entry)
        existing.add(key)
        imported += 1
    db.commit()
    return ImportResult(imported=imported, skipped=skipped)


@router.get("/{entry_id}", response_model=WorkLogOut)
def read_entry(entry_id: int, db: Db) -> WorkLogOut:
    return out(get_entry(db, entry_id))


@router.put("/{entry_id}", response_model=WorkLogOut)
def update_entry(entry_id: int, fields: WorkLogUpdate, db: Db) -> WorkLogOut:
    entry = get_entry(db, entry_id)
    apply(db, entry, fields)
    entry.is_demo = False  # once edited it is the user's own entry
    db.commit()
    db.refresh(entry)
    return out(entry)


@router.delete("/{entry_id}", status_code=204)
def delete_entry(entry_id: int, db: Db) -> None:
    db.delete(get_entry(db, entry_id))
    db.commit()
