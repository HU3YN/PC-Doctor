"""Getting a PC's problem into the system when the usual route does not apply:

* the collector, downloaded from this server onto a USB stick
* a photo of an error screen, read by OCR
* a guided checklist for a PC that will not start at all
"""

from __future__ import annotations

import hashlib
import socket
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pcdoctor_analysis.errortext import interpret
from pcdoctor_analysis.noboot import SYMPTOMS
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..config import Settings, get_settings
from ..db import get_db
from ..deps import Master
from ..models import WorkLogEntry
from ..schemas import SimilarCase, WorkLogBrief
from ..services import collector_build
from ..services import photo as photo_service
from ..services.similarity import Query as SimilarityQuery
from ..services.similarity import find_similar
from .runs import read_limited

router = APIRouter(prefix="/api", tags=["intake"])

Db = Annotated[Session, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]

MAX_PHOTO_MB = 25
# Exactly what goes on the USB stick. Tests and the tools folder's other
# contents stay behind.


def collector_dir(settings: Settings) -> Path | None:
    folder = settings.collector_dir
    if folder is None:
        folder = Path(__file__).resolve().parents[3] / "collector"  # running from a checkout
    return folder if (folder / "Collect-PCDoctor.ps1").is_file() else None


def lan_addresses() -> list[str]:
    """This computer's addresses on the local network (best effort, no traffic sent)."""
    if Path("/.dockerenv").exists():
        return []  # inside a container the address is the container's, not the PC's
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))  # UDP: nothing is actually sent
            found.append(probe.getsockname()[0])
    except OSError:
        pass
    return [a for a in found if not a.startswith("127.")]


@router.get("/collector")
def collector_info(settings: Config) -> dict[str, Any]:
    folder = collector_dir(settings)
    zipped = collector_build.collector_zip(folder) if folder else b""
    return {
        "available": folder is not None,
        # Compare with the release on GitHub, or check its attestation:
        # gh attestation verify PCDoctor-collector.zip --repo HU3YN/PC-Doctor
        "sha256": hashlib.sha256(zipped).hexdigest() if folder else None,
        "includes_presentmon": bool(folder and collector_build.trusted_tools(folder)),
        "lan_addresses": lan_addresses(),
        "photo_reading": photo_service.available(),
    }


def _zip_response(data: bytes, filename: str) -> Response:
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/collector.zip")
def collector_zip(settings: Config) -> Response:
    """The collector as one zip: unpack it onto a USB stick and double-click PCDoctor.cmd.

    Built reproducibly (services/collector_build.py): the same commit gives the
    same bytes as the attested GitHub release."""
    folder = collector_dir(settings)
    if folder is None:
        raise HTTPException(status_code=404, detail="The collector is not on this server.")
    return _zip_response(collector_build.collector_zip(folder), "PCDoctor-collector.zip")


@router.get("/collector/presentmon.zip")
def presentmon_zip(settings: Config) -> Response:
    """Intel's PresentMon, if it was fetched on this computer and is the pinned
    file. Unpacks into the collector's folder (tools/)."""
    folder = collector_dir(settings)
    data = collector_build.presentmon_zip(folder) if folder else None
    if data is None:
        raise HTTPException(status_code=404, detail="PresentMon is not on this server.")
    return _zip_response(data, "PCDoctor-collector-PresentMon.zip")


@router.get("/noboot")
def no_boot_guide() -> list[dict[str, Any]]:
    return [symptom.to_dict() for symptom in SYMPTOMS]


@router.post("/photos")
async def read_photo(
    db: Db,
    _: Master,
    file: Annotated[UploadFile, File(description="A photo of the error screen (JPG or PNG)")],
) -> dict[str, Any]:
    """Read an error photo: the text on it, any stop codes, and earlier jobs with them.

    The photo is not stored.
    """
    data = await read_limited(file, MAX_PHOTO_MB * 1024 * 1024)
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    try:
        # OCR takes a while: on a thread, so other requests are not held up.
        text = await run_in_threadpool(photo_service.read_text, data)
    except photo_service.OcrUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
    except photo_service.PhotoError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None

    reading = interpret(text)
    codes = [entry.hex for entry in reading.stop_codes] + reading.unknown_codes
    cases: list[SimilarCase] = []
    if codes or reading.drivers:
        matches = find_similar(
            list(db.scalars(select(WorkLogEntry))),
            SimilarityQuery(codes=codes, text=" ".join(reading.drivers)),
            limit=5,
        )
        cases = [
            SimilarCase(
                entry=WorkLogBrief.model_validate(m.entry), score=m.score, reasons=m.reasons
            )
            for m in matches
        ]
    return {
        "text": text[:4000],
        "is_blue_screen": reading.is_blue_screen,
        "stop_codes": [entry.to_dict() for entry in reading.stop_codes],
        "unknown_codes": reading.unknown_codes,
        "drivers": reading.drivers,
        "cases": [case.model_dump(mode="json") for case in cases],
    }
