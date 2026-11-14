"""The photo inbox: photos of PCs that will not start, sent from a phone.

The master makes a link (shown as a QR code). A phone that opens the link can
add photos and nothing else - no sign-in, and no way to read anything back.
Each photo is read by OCR on arrival and waits in the master's inbox.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pcdoctor_analysis.errortext import interpret
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..config import Settings, get_settings
from ..db import get_db, utcnow
from ..deps import ClientKey, Master
from ..models import Photo, PhotoLink, WorkLogEntry, new_id
from ..schemas import SimilarCase, WorkLogBrief
from ..services import ai as ai_service
from ..services import auth as auth_service
from ..services import photo as photo_service
from ..services.similarity import Query as SimilarityQuery
from ..services.similarity import find_similar
from .runs import read_limited

router = APIRouter(prefix="/api", tags=["photo inbox"])

Db = Annotated[Session, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]

MAX_PHOTO_MB = 25
LINK_HOURS = 12


class NewLink(BaseModel):
    label: str = Field(default="", max_length=200)


def link_for(db: Session, token: str) -> PhotoLink:
    link = db.scalar(
        select(PhotoLink).where(PhotoLink.token_hash == auth_service.token_hash(token))
    )
    if link is None or link.expires_at < utcnow():
        raise HTTPException(
            status_code=404, detail="This photo link has expired. Ask for a new QR code."
        )
    return link


def photo_out(
    db: Session, photo: Photo, entries: list[WorkLogEntry] | None = None
) -> dict[str, Any]:
    reading = photo.reading or {}
    codes = [code["hex"] for code in reading.get("stop_codes", [])] + reading.get(
        "unknown_codes", []
    )
    cases: list[dict[str, Any]] = []
    if codes or reading.get("drivers"):
        if entries is None:
            entries = list(db.scalars(select(WorkLogEntry)))
        matches = find_similar(
            [e for e in entries if e.id != photo.work_log_id],
            SimilarityQuery(codes=codes, text=" ".join(reading.get("drivers", []))),
            limit=4,
        )
        cases = [
            SimilarCase(
                entry=WorkLogBrief.model_validate(m.entry), score=m.score, reasons=m.reasons
            ).model_dump(mode="json")
            for m in matches
        ]
    return {
        "id": photo.id,
        "created_at": photo.created_at,
        "label": photo.label,
        "text": photo.text,
        "stop_codes": reading.get("stop_codes", []),
        "unknown_codes": reading.get("unknown_codes", []),
        "drivers": reading.get("drivers", []),
        "is_blue_screen": bool(reading.get("is_blue_screen")),
        "ai": photo.ai,
        "work_log_id": photo.work_log_id,
        "cases": cases,
    }


@router.post("/photo-links")
def create_link(body: NewLink, db: Db, _: Master) -> dict[str, Any]:
    """A new link for sending photos in. Show it as a QR code; it lasts 12 hours."""
    token = auth_service.new_token()
    link = PhotoLink(
        token_hash=auth_service.token_hash(token),
        label=" ".join(body.label.split()),
        expires_at=utcnow() + timedelta(hours=LINK_HOURS),
    )
    db.add(link)
    db.commit()
    return {
        "token": token,
        "path": f"/snap/{token}",
        "label": link.label,
        "expires_at": link.expires_at,
    }


@router.get("/photo-links/{token}")
def check_link(token: str, db: Db) -> dict[str, Any]:
    """What the phone's page needs: is the link still good, and what is it for."""
    link = link_for(db, token)
    return {"label": link.label, "expires_at": link.expires_at}


@router.post("/photo-links/{token}/photos", status_code=201)
async def send_photo(
    token: str,
    db: Db,
    settings: Config,
    key: ClientKey,
    file: Annotated[UploadFile, File(description="A photo")],
) -> dict[str, Any]:
    """Add a photo to the master's inbox. Tells the sender only that it arrived."""
    link = link_for(db, token)
    if not auth_service.guest_uploads.allow(f"photo:{key}"):
        raise HTTPException(status_code=429, detail="Too many photos from here. Try again later.")
    data = await read_limited(file, MAX_PHOTO_MB * 1024 * 1024)
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    try:
        jpeg = await run_in_threadpool(photo_service.to_jpeg, data)
    except photo_service.PhotoError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    except photo_service.OcrUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
    try:
        text = await run_in_threadpool(photo_service.read_text, jpeg)
    except (photo_service.OcrUnavailable, photo_service.PhotoError):
        text = ""  # the photo is still worth having without the text
    reading = interpret(text)
    photo = Photo(
        id=new_id(),
        label=link.label,
        file_bytes=len(jpeg),
        text=text[:4000],
        reading={
            "stop_codes": [entry.to_dict() for entry in reading.stop_codes],
            "unknown_codes": reading.unknown_codes,
            "drivers": reading.drivers,
            "is_blue_screen": reading.is_blue_screen,
        },
    )
    photo.file_name = f"{photo.id}.jpg"
    settings.photos_dir.mkdir(parents=True, exist_ok=True)
    path = settings.photos_dir / photo.file_name
    path.write_bytes(jpeg)
    try:
        db.add(photo)
        db.commit()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {"received": True}


def get_photo(db: Session, photo_id: str) -> Photo:
    photo = db.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found.")
    return photo


@router.get("/inbox")
def list_inbox(db: Db, _: Master) -> dict[str, Any]:
    photos = list(db.scalars(select(Photo).order_by(Photo.created_at.desc()).limit(200)))
    entries = list(db.scalars(select(WorkLogEntry)))
    return {
        "items": [photo_out(db, photo, entries) for photo in photos],
        "waiting": sum(1 for photo in photos if photo.work_log_id is None),
    }


@router.get("/inbox/{photo_id}/image")
def photo_image(photo_id: str, db: Db, settings: Config, _: Master) -> FileResponse:
    photo = get_photo(db, photo_id)
    path = settings.photos_dir / photo.file_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The photo file is no longer on disk.")
    return FileResponse(
        path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"}
    )


@router.post("/inbox/{photo_id}/describe")
def describe_photo(photo_id: str, db: Db, settings: Config, _: Master) -> dict[str, Any]:
    """Ask the AI helper what the photo shows. Sends the photo to the AI provider."""
    photo = get_photo(db, photo_id)
    path = settings.photos_dir / photo.file_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The photo file is no longer on disk.")
    try:
        photo.ai = ai_service.describe_photo(settings, path.read_bytes(), photo.text)
    except ai_service.AiUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
    except ai_service.AiError as error:
        raise HTTPException(status_code=502, detail=str(error)) from None
    db.commit()
    return photo_out(db, photo)


class LinkEntry(BaseModel):
    work_log_id: int | None


@router.patch("/inbox/{photo_id}")
def mark_logged(photo_id: str, body: LinkEntry, db: Db, _: Master) -> dict[str, Any]:
    """Tie a photo to the work-log entry made from it (or untie it)."""
    photo = get_photo(db, photo_id)
    if body.work_log_id is not None and db.get(WorkLogEntry, body.work_log_id) is None:
        raise HTTPException(status_code=422, detail="That work-log entry does not exist.")
    photo.work_log_id = body.work_log_id
    db.commit()
    return photo_out(db, photo)


@router.delete("/inbox/{photo_id}", status_code=204)
def delete_photo(photo_id: str, db: Db, settings: Config, _: Master) -> None:
    photo = get_photo(db, photo_id)
    path = settings.photos_dir / photo.file_name
    db.delete(photo)
    db.commit()
    path.unlink(missing_ok=True)
