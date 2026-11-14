"""Build the collector zip the same way every time.

The same commit always gives the same bytes - the same file order, a fixed
timestamp, fixed permissions, fixed line endings - so the zip the server
offers at /api/collector.zip has the same SHA-256 as the one the release
workflow builds, attests and publishes (.github/workflows/release-collector.yml).
A technician can then check the copy they are about to run as administrator:

    gh attestation verify PCDoctor-collector.zip --repo HU3YN/PC-Doctor

PresentMon is not in this zip. It is Intel's program, fetched and checked by
Get-Tools.ps1, and offered as a separate download (presentmon_zip) that
unpacks into the same folder.

Standard library only, so the release workflow can run it without installing
anything:

    python api/pcdoctor_api/services/collector_build.py collector dist/PCDoctor-collector.zip
"""

from __future__ import annotations

import hashlib
import io
import re
import sys
import zipfile
from pathlib import Path

COLLECTOR_FILES = (
    "PCDoctor.cmd",
    "Collect-PCDoctor.ps1",
    "PCDoctorCollector.psm1",
    "Get-Tools.ps1",
    "README.md",
)
FOLDER = "PCDoctor-collector"
FIXED_TIME = (2026, 1, 1, 0, 0, 0)  # every entry gets this date: no build time in the bytes
_PINNED_SHA256 = re.compile(r"\$Sha256\s*=\s*'([0-9A-Fa-f]{64})'")


def normalised(name: str, data: bytes) -> bytes:
    """CRLF for the .cmd launcher (cmd.exe misreads LF-only files), LF for the
    rest - whatever line endings this checkout happens to have."""
    data = data.replace(b"\r\n", b"\n")
    return data.replace(b"\n", b"\r\n") if name.endswith(".cmd") else data


def _add(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    entry = zipfile.ZipInfo(name, date_time=FIXED_TIME)
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry.create_system = 0  # "made on Windows": no Unix owner or mode bits
    entry.external_attr = 0
    archive.writestr(entry, data, compresslevel=9)


def collector_zip(folder: Path) -> bytes:
    """The collector folder's known files as one zip. Missing files are skipped."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in COLLECTOR_FILES:
            path = folder / name
            if path.is_file():
                _add(archive, f"{FOLDER}/{name}", normalised(name, path.read_bytes()))
    return buffer.getvalue()


def pinned_presentmon_hashes(folder: Path) -> set[str]:
    """The SHA-256 that Get-Tools.ps1 pins for PresentMon (its one source of truth)."""
    try:
        script = (folder / "Get-Tools.ps1").read_text(encoding="utf-8")
    except OSError:
        return set()
    return {match.lower() for match in _PINNED_SHA256.findall(script)}


def trusted_tools(folder: Path) -> list[Path]:
    """PresentMon files in tools/ whose SHA-256 is the pinned one. Anything
    else in that folder - a swapped or newer file - is never offered."""
    pinned = pinned_presentmon_hashes(folder)
    return [
        tool
        for tool in sorted((folder / "tools").glob("PresentMon*.exe"))
        if hashlib.sha256(tool.read_bytes()).hexdigest() in pinned
    ]


def presentmon_zip(folder: Path) -> bytes | None:
    """The pinned PresentMon, laid out to unpack into the collector's folder."""
    tools = trusted_tools(folder)
    if not tools:
        return None
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for tool in tools:
            _add(archive, f"{FOLDER}/tools/{tool.name}", tool.read_bytes())
    return buffer.getvalue()


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: collector_build.py <collector folder> <output zip>", file=sys.stderr)
        return 2
    folder, out = Path(argv[1]), Path(argv[2])
    if not (folder / "Collect-PCDoctor.ps1").is_file():
        print(f"{folder} is not the collector folder", file=sys.stderr)
        return 2
    data = collector_zip(folder)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"{hashlib.sha256(data).hexdigest()}  {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
