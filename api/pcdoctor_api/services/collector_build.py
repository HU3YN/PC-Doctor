"""Build the collector zip the same way every time.

The same commit always gives the same bytes - the same file order, a fixed
timestamp, fixed permissions, fixed line endings - so the zip the server
offers at /api/collector.zip has the same SHA-256 as the one the release
workflow builds, attests and publishes (.github/workflows/release-collector.yml).
A technician can then check the copy they are about to run as administrator:

    gh attestation verify PCDoctor-collector.zip --repo HU3YN/PC-Doctor

PresentMon (Intel's frame-time recorder) is in the zip too, unmodified, as
tools/PresentMon-<version>-x64.exe, so one download is all a PC needs. Its
binary is not in git: fetch_presentmon downloads the release Get-Tools.ps1
pins and keeps it only if its SHA-256 is the pinned one, and collector_zip
checks that hash again before packing it. The collector checks Intel's
signature before running it. Intel's licence (MIT) travels with it as
PresentMon-LICENSE.txt. A folder without the pinned file still builds - the
zip is then the scripts alone, and the collector fetches PresentMon itself.

Standard library only, so the release workflow and the Docker build can run
it without installing anything:

    python api/pcdoctor_api/services/collector_build.py fetch-presentmon collector
    python api/pcdoctor_api/services/collector_build.py --require-presentmon \
        collector dist/PCDoctor-collector.zip
"""

from __future__ import annotations

import hashlib
import io
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

COLLECTOR_FILES = (
    "PCDoctor.cmd",
    "Collect-PCDoctor.ps1",
    "PCDoctorCollector.psm1",
    "Get-Tools.ps1",
    "README.md",
    "PresentMon-LICENSE.txt",  # Intel's licence: it must travel with their program
)
FOLDER = "PCDoctor-collector"
FIXED_TIME = (2026, 1, 1, 0, 0, 0)  # every entry gets this date: no build time in the bytes
_PINNED_SHA256 = re.compile(r"\$Sha256\s*=\s*'([0-9A-Fa-f]{64})'")
# Digits and dots only: the version goes into a URL and a file name.
_PINNED_VERSION = re.compile(r"\$Version\s*=\s*'(\d+(?:\.\d+){1,3})'")
PRESENTMON_URL = "https://github.com/GameTechDev/PresentMon/releases/download/v{version}/{name}"
# The real file is about 1 MB. Anything far bigger is not it, so stop reading.
MAX_PRESENTMON_BYTES = 32 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 60


class FetchError(Exception):
    """PresentMon could not be fetched, or what arrived was not the pinned file."""


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
    """The collector folder's known files, and the pinned PresentMon if it is
    there, as one zip. Missing files are skipped."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in COLLECTOR_FILES:
            path = folder / name
            if path.is_file():
                _add(archive, f"{FOLDER}/{name}", normalised(name, path.read_bytes()))
        # Byte for byte as Intel published it: no line-ending changes here.
        for tool in trusted_tools(folder):
            _add(archive, f"{FOLDER}/tools/{tool.name}", tool.read_bytes())
    return buffer.getvalue()


def _get_tools_script(folder: Path) -> str:
    try:
        return (folder / "Get-Tools.ps1").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def pinned_presentmon_hashes(folder: Path) -> set[str]:
    """The SHA-256 that Get-Tools.ps1 pins for PresentMon (its one source of truth)."""
    return {match.lower() for match in _PINNED_SHA256.findall(_get_tools_script(folder))}


def pinned_presentmon(folder: Path) -> tuple[str, str] | None:
    """(file name, SHA-256) of the one PresentMon release Get-Tools.ps1 pins,
    or None if the script does not name exactly one version and one hash."""
    script = _get_tools_script(folder)
    versions = set(_PINNED_VERSION.findall(script))
    hashes = pinned_presentmon_hashes(folder)
    if len(versions) != 1 or len(hashes) != 1:
        return None
    return f"PresentMon-{versions.pop()}-x64.exe", hashes.pop()


def trusted_tools(folder: Path) -> list[Path]:
    """The pinned PresentMon in tools/, if it is there: the file name
    Get-Tools.ps1 gives it, with the SHA-256 Get-Tools.ps1 pins. Anything else
    in that folder - a swapped file, a newer one, the right file under another
    name - is never packed, so two builds of one commit cannot differ."""
    pinned = pinned_presentmon(folder)
    if pinned is None:
        return []
    name, sha256 = pinned
    tool = folder / "tools" / name
    try:
        if tool.is_file() and hashlib.sha256(tool.read_bytes()).hexdigest() == sha256:
            return [tool]
    except OSError:
        pass
    return []


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    """GitHub redirects a release download to its file store. Follow that, but
    never onto anything that is not https."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith("https://"):
            raise FetchError(f"refusing a redirect that leaves https: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(url: str, limit: int) -> bytes:
    """The body at an https URL, or FetchError. Reads at most limit bytes."""
    if not url.lower().startswith("https://"):
        raise FetchError(f"not an https address: {url}")
    opener = urllib.request.build_opener(_HttpsOnly)
    request = urllib.request.Request(url, headers={"User-Agent": "pcdoctor-collector-build"})
    try:
        with opener.open(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            data = response.read(limit + 1)
    except (OSError, ValueError) as error:  # URLError and timeouts are OSErrors
        raise FetchError(f"download failed: {error}") from error
    if len(data) > limit:
        raise FetchError(f"the download is larger than {limit} bytes, so it is not PresentMon")
    return data


def fetch_presentmon(folder: Path) -> Path:
    """Put the pinned PresentMon in folder/tools and return its path.

    Does nothing if the right file is already there. A download whose SHA-256
    is not the pinned one is never written under the real name, and its
    temporary file is deleted. Raises FetchError when it cannot be done."""
    pinned = pinned_presentmon(folder)
    if pinned is None:
        raise FetchError(f"{folder / 'Get-Tools.ps1'} does not pin one PresentMon version and hash")
    name, sha256 = pinned
    target = folder / "tools" / name
    if trusted_tools(folder):
        return target
    version = name.removeprefix("PresentMon-").removesuffix("-x64.exe")
    data = _download(PRESENTMON_URL.format(version=version, name=name), MAX_PRESENTMON_BYTES)
    partial = target.with_name(target.name + ".download")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Check what is on disk, not what was in memory, then rename into place.
        partial.write_bytes(data)
        actual = hashlib.sha256(partial.read_bytes()).hexdigest()
        if actual != sha256:
            raise FetchError(
                "the downloaded file is not the pinned PresentMon, so it was deleted\n"
                f"  expected SHA-256: {sha256}\n"
                f"  actual SHA-256:   {actual}"
            )
        partial.replace(target)
    except OSError as error:
        raise FetchError(f"could not save {target}: {error}") from error
    finally:
        partial.unlink(missing_ok=True)
    return target


USAGE = """usage: collector_build.py [--require-presentmon] <collector folder> <output zip>
       collector_build.py fetch-presentmon <collector folder>"""


def _is_collector_folder(folder: Path) -> bool:
    if (folder / "Collect-PCDoctor.ps1").is_file():
        return True
    print(f"{folder} is not the collector folder", file=sys.stderr)
    return False


def _fetch_command(args: list[str]) -> int:
    if len(args) != 1:
        print(USAGE, file=sys.stderr)
        return 2
    folder = Path(args[0])
    if not _is_collector_folder(folder):
        return 2
    try:
        target = fetch_presentmon(folder)
    except FetchError as error:
        print(f"PresentMon was not fetched: {error}", file=sys.stderr)
        return 1
    print(f"{hashlib.sha256(target.read_bytes()).hexdigest()}  {target}")
    return 0


def main(argv: list[str]) -> int:
    args = argv[1:]
    if args[:1] == ["fetch-presentmon"]:
        return _fetch_command(args[1:])
    # A release must not quietly go out without PresentMon: with this flag a
    # zip that would lack it is an error, and nothing is written.
    require_presentmon = "--require-presentmon" in args
    args = [arg for arg in args if arg != "--require-presentmon"]
    if len(args) != 2 or any(arg.startswith("--") for arg in args):
        print(USAGE, file=sys.stderr)
        return 2
    folder, out = Path(args[0]), Path(args[1])
    if not _is_collector_folder(folder):
        return 2
    if require_presentmon:
        missing = [] if trusted_tools(folder) else ["the pinned PresentMon in tools/"]
        if not (folder / "PresentMon-LICENSE.txt").is_file():
            missing.append("PresentMon-LICENSE.txt")
        if missing:
            print(
                f"{folder} lacks {' and '.join(missing)}. "
                f"Run: collector_build.py fetch-presentmon {folder}",
                file=sys.stderr,
            )
            return 1
    data = collector_zip(folder)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"{hashlib.sha256(data).hexdigest()}  {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
