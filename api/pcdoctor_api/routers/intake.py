"""Getting a PC's problem into the system when the usual route does not apply:

* the collector, downloaded from this server onto a USB stick
* a photo of an error screen, read by OCR
* a guided checklist for a PC that will not start at all
"""

from __future__ import annotations

import io
import socket
import zipfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pcdoctor_analysis.errortext import interpret
from pcdoctor_analysis.noboot import SYMPTOMS
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..deps import Master
from ..models import WorkLogEntry
from ..schemas import SimilarCase, WorkLogBrief
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
COLLECTOR_FILES = (
    "PCDoctor.cmd",
    "Collect-PCDoctor.ps1",
    "PCDoctorCollector.psm1",
    "Get-Tools.ps1",
    "README.md",
)


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
    tools = sorted(p.name for p in (folder / "tools").glob("PresentMon*.exe")) if folder else []
    return {
        "available": folder is not None,
        "includes_presentmon": bool(tools),
        "lan_addresses": lan_addresses(),
        "photo_reading": photo_service.available(),
    }


@router.get("/collector.zip")
def collector_zip(settings: Config) -> Response:
    """The collector as one zip: unpack it onto a USB stick and double-click PCDoctor.cmd."""
    folder = collector_dir(settings)
    if folder is None:
        raise HTTPException(status_code=404, detail="The collector is not on this server.")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in COLLECTOR_FILES:
            path = folder / name
            if not path.is_file():
                continue
            data = path.read_bytes()
            if name.endswith(".cmd"):
                # cmd.exe needs CRLF line endings, whatever this server's checkout has.
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            archive.writestr(f"PCDoctor-collector/{name}", data)
        # PresentMon travels along if it has been fetched on this computer.
        for tool in sorted((folder / "tools").glob("PresentMon*.exe")):
            archive.write(tool, f"PCDoctor-collector/tools/{tool.name}")
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="PCDoctor-collector.zip"'},
    )


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
        text = photo_service.read_text(data)
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
