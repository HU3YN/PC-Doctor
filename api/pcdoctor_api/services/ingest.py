"""Take an uploaded run, check it, analyse it and store it.

An upload is a .zip made by the collector (or, for convenience, a bare
PresentMon .csv). It is untrusted input, so it is unpacked defensively:
only known file names are read, sizes are capped while reading, and nothing
in the archive can choose where a file is written.
"""

from __future__ import annotations

import hashlib
import io
import lzma
import tempfile
import time
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pcdoctor_analysis import AnalysisResult, analyze_run_dir
from pcdoctor_analysis.loader import load_run_dir
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import metrics
from ..config import Settings
from ..models import Finding, Run, new_id

# The only files a run may contain. Anything else in the archive is ignored.
RUN_FILES = frozenset(
    {
        "manifest.json",
        "specs.json",
        "events.json",
        "disks.json",
        "presentmon.csv",
        "sensors.csv",
        "sensors_raw.json",
        "collector.log",
    }
)
MAX_ARCHIVE_ENTRIES = 200
CHUNK = 1024 * 1024

# What zipfile raises on a damaged or hostile archive, besides BadZipFile: a
# name that is not valid UTF-8 (UnicodeDecodeError, a ValueError), an
# unsupported compression method or encryption (NotImplementedError),
# compressed bytes that do not decompress (zlib.error, lzma.LZMAError, OSError
# from bz2) or that stop early (EOFError).
_ZIP_ERRORS = (
    zipfile.BadZipFile,
    ValueError,
    NotImplementedError,
    RuntimeError,
    EOFError,
    OSError,
    zlib.error,
    lzma.LZMAError,
)


class UploadError(ValueError):
    """The upload cannot be used. The message is safe to show to the user."""


@dataclass
class Ingested:
    run: Run
    created: bool  # False = this exact file was uploaded before


def _is_zip(data: bytes) -> bool:
    return data[:4] in (b"PK\x03\x04", b"PK\x05\x06")


def _looks_like_presentmon_csv(data: bytes) -> bool:
    head = data[:4096].decode("utf-8-sig", errors="replace").splitlines()
    if not head:
        return False
    columns = {c.strip().lower() for c in head[0].split(",")}
    return bool(columns & {"msbetweenpresents", "frametime"})


def unpack(data: bytes, destination: Path, settings: Settings) -> list[str]:
    """Write the run's known files into ``destination``; return their names."""
    limit = settings.max_unpacked_mb * 1024 * 1024
    too_big = UploadError(
        f"The run unpacks to more than {settings.max_unpacked_mb} MB, which is over the limit."
    )
    if not _is_zip(data):
        if _looks_like_presentmon_csv(data):
            if len(data) > limit:
                raise too_big
            (destination / "presentmon.csv").write_bytes(data)
            return ["presentmon.csv"]
        raise UploadError(
            "This is not a PC Doctor run. Upload the .zip the collector made, "
            "or a PresentMon .csv file."
        )
    damaged = UploadError("The zip file is damaged and cannot be opened.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except _ZIP_ERRORS:
        raise damaged from None

    with archive:
        entries = archive.infolist()
        if len(entries) > MAX_ARCHIVE_ENTRIES:
            raise UploadError("The zip has far more files than a PC Doctor run contains.")
        # Accept files at the top level or inside one folder (people zip the
        # run folder itself). Only the file's own name is used - never its path.
        chosen: dict[str, zipfile.ZipInfo] = {}
        for info in entries:
            if info.is_dir():
                continue
            path = PurePosixPath(info.filename.replace("\\", "/"))
            name = path.name.lower()
            if name not in RUN_FILES or len(path.parts) > 2:
                continue
            previous = chosen.get(name)
            if previous is None or len(path.parts) < len(
                PurePosixPath(previous.filename.replace("\\", "/")).parts
            ):
                chosen[name] = info
        if not chosen:
            raise UploadError(
                "No PC Doctor files were found in this zip (expected manifest.json, "
                "specs.json, events.json, ...)."
            )
        if sum(info.file_size for info in chosen.values()) > limit:
            raise too_big
        if any(info.flag_bits & 0x1 for info in chosen.values()):
            raise UploadError("The zip is password-protected.")
        written = 0
        for name, info in chosen.items():
            # The declared size can lie, so count the bytes actually read.
            # Errors from reading the archive are the upload's fault; errors
            # from writing the destination are ours and are not caught.
            try:
                source = archive.open(info)
            except _ZIP_ERRORS:
                raise damaged from None
            with source, open(destination / name, "wb") as target:
                while True:
                    try:
                        chunk = source.read(CHUNK)
                    except _ZIP_ERRORS:
                        raise damaged from None
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > limit:
                        raise too_big
                    target.write(chunk)
    return sorted(chosen)


def _clean_zip(folder: Path, names: list[str]) -> bytes:
    """Re-pack only the known files, so what is stored is exactly what was read."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.write(folder / name, arcname=name)
    return buffer.getvalue()


def apply_result(run: Run, result: AnalysisResult) -> None:
    """Copy an analysis result onto a run row (new upload or re-analysis)."""
    stats = result.frame_stats or {}
    device = result.device
    run.verdict = result.verdict
    run.headline = result.headline[:300]
    run.critical_count = result.counts["critical"]
    run.warning_count = result.counts["warning"]
    run.info_count = result.counts["info"]
    run.cpu = (device.get("cpu") or None) and str(device["cpu"])[:200]
    run.gpu = (device.get("gpu") or None) and str(device["gpu"])[:200]
    run.ram_gb = device.get("ram_gb")
    run.avg_fps = stats.get("avg_fps")
    run.fps_1pct_low = stats.get("fps_1pct_low")
    run.rules_version = result.rules_version
    body = result.to_dict()
    body.pop("findings")  # stored in their own table
    run.result = body
    run.findings = [
        Finding(
            position=position,
            code=finding.code,
            category=finding.category,
            severity=finding.severity.value,
            title=finding.title[:300],
            summary=finding.summary,
            next_checks=list(finding.next_checks),
            evidence=dict(finding.evidence),
            error_codes=list(finding.error_codes),
        )
        for position, finding in enumerate(result.findings)
    ]


def ingest(
    db: Session,
    settings: Settings,
    data: bytes,
    *,
    label: str = "",
    is_demo: bool = False,
    source: str = "master",
) -> Ingested:
    if not data:
        raise UploadError("The uploaded file is empty.")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise UploadError(f"The file is larger than the {settings.max_upload_mb} MB limit.")

    started = time.perf_counter()
    content_hash = hashlib.sha256(data).hexdigest()
    existing = db.scalar(select(Run).where(Run.content_hash == content_hash))
    if existing is not None:
        return Ingested(existing, created=False)

    with tempfile.TemporaryDirectory(prefix="pcdoctor-") as temp:
        folder = Path(temp)
        names = unpack(data, folder, settings)
        loaded = load_run_dir(folder)
        result = analyze_run_dir(folder)
        stored = _clean_zip(folder, names)

    manifest = loaded.manifest
    collector = manifest.get("collector") if isinstance(manifest.get("collector"), dict) else {}
    run = Run(
        id=new_id(),
        captured_at=loaded.captured_at,
        label=(label or str(manifest.get("label") or "")).strip()[:200],
        mode=str(manifest.get("mode") or ("capture" if loaded.frames else ""))[:20],
        collector_version=str(collector.get("version") or "")[:40],
        content_hash=content_hash,
        file_bytes=len(stored),
        is_demo=is_demo or bool(manifest.get("synthetic")),
        source=source,
    )
    run.file_name = f"{run.id}.zip"
    apply_result(run, result)

    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    path = settings.runs_dir / run.file_name
    path.write_bytes(stored)
    try:
        db.add(run)
        db.commit()
    except Exception:
        path.unlink(missing_ok=True)  # do not leave a file with no database row
        raise
    metrics.RUNS.labels(source, run.verdict).inc()
    metrics.ANALYSIS.observe(time.perf_counter() - started)
    return Ingested(run, created=True)


def reanalyze(db: Session, settings: Settings, run: Run) -> Run:
    """Run the current rules over a stored run again."""
    path = settings.runs_dir / run.file_name
    if not path.is_file():
        raise UploadError("The original upload for this run is no longer on disk.")
    with tempfile.TemporaryDirectory(prefix="pcdoctor-") as temp:
        folder = Path(temp)
        unpack(path.read_bytes(), folder, settings)
        result = analyze_run_dir(folder)
    apply_result(run, result)
    db.commit()
    return run


def delete_run(db: Session, settings: Settings, run: Run) -> None:
    path = settings.runs_dir / run.file_name
    db.delete(run)
    db.commit()
    path.unlink(missing_ok=True)
