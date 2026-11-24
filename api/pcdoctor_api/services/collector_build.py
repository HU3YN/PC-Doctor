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

What the collector needs to read CPU temperature is in the zip too, so
nothing else has to be downloaded on the PC: PawnIO's official installer,
unmodified, as tools/PawnIO_setup.exe, and LibreHardwareMonitorLib with the
libraries it needs on .NET Framework 4.7.2, as tools/lhm/*.dll. All of them
are pinned in temperature-tools.json: the installer by its SHA-256, each
library by the SHA-256 of its NuGet package (checked when it is fetched) and
of the one DLL taken from it (checked again when it is packed). The kit is
all or nothing: if any one file is missing or is not the pinned one, none of
them is packed. Their licences are in licences/.

Standard library only, so the release workflow and the Docker build can run
it without installing anything:

    python api/pcdoctor_api/services/collector_build.py fetch-tools collector
    python api/pcdoctor_api/services/collector_build.py --require-presentmon \
        --require-temperature-tools collector dist/PCDoctor-collector.zip
"""

from __future__ import annotations

import hashlib
import io
import json
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
    "temperature-tools.json",  # the pins: the collector checks the files against them
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

TEMPERATURE_PINS = "temperature-tools.json"
LIBRARY_FOLDER = "lhm"  # tools/lhm/
NUGET_URL = "https://api.nuget.org/v3-flatcontainer/{id}/{version}/{id}.{version}.nupkg"
# The installer is about 3.4 MB, the biggest package about 7 MB.
MAX_INSTALLER_BYTES = 16 * 1024 * 1024
MAX_NUPKG_BYTES = 32 * 1024 * 1024
MAX_DLL_BYTES = 16 * 1024 * 1024
# The licence texts in licences/ go into the zip under licences/. Only these
# are required for a release that carries the temperature tools.
LICENCES = "licences"
TEMPERATURE_LICENCES = (
    "PawnIO-COPYING.txt",
    "PawnIO-SOURCE.txt",
    "MPL-2.0.txt",
    "HidSharp-LICENSE.txt",
    "dotnet-MIT-LICENSE.txt",
    "LIBRARIES.txt",
)
_SHA256 = re.compile(r"[0-9A-Fa-f]{64}")
# These go into URLs and file names: nothing that could climb out of tools/.
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SAFE_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")


class FetchError(Exception):
    """A pinned tool could not be fetched, or what arrived was not the pinned file."""


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
    """The collector folder's known files and licences, and the pinned
    PresentMon and temperature tools if they are there, as one zip. Missing
    files are skipped."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in COLLECTOR_FILES:
            path = folder / name
            if path.is_file():
                _add(archive, f"{FOLDER}/{name}", normalised(name, path.read_bytes()))
        for licence in licence_files(folder):
            _add(
                archive,
                f"{FOLDER}/{LICENCES}/{licence.name}",
                normalised(licence.name, licence.read_bytes()),
            )
        # Byte for byte as Intel published it: no line-ending changes here.
        for tool in trusted_tools(folder):
            _add(archive, f"{FOLDER}/tools/{tool.name}", tool.read_bytes())
        # The same for PawnIO's installer and the DLLs, all checked again just now.
        for tool in trusted_temperature_tools(folder):
            _add(archive, f"{FOLDER}/{tool.relative_to(folder).as_posix()}", tool.read_bytes())
    return buffer.getvalue()


def licence_files(folder: Path) -> list[Path]:
    """The .txt files in licences/, by name."""
    try:
        found = [path for path in (folder / LICENCES).glob("*.txt") if path.is_file()]
    except OSError:
        return []
    return sorted(found, key=lambda path: path.name)


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
    """The body at an https URL, or FetchError. Reads at most limit bytes, so
    something far bigger than the pinned file is never held whole."""
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
        raise FetchError(f"the download is larger than {limit} bytes, so it is not the pinned file")
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
    _save_verified(target, data, sha256, "PresentMon")
    return target


def _save_verified(target: Path, data: bytes, sha256: str, what: str) -> None:
    """Write data to target only if its SHA-256 is the pinned one. A file with
    any other hash is never written under the real name, and its temporary
    file is deleted. Raises FetchError."""
    partial = target.with_name(target.name + ".download")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Check what is on disk, not what was in memory, then rename into place.
        partial.write_bytes(data)
        actual = hashlib.sha256(partial.read_bytes()).hexdigest()
        if actual != sha256.lower():
            raise FetchError(
                f"the downloaded file is not the pinned {what}, so it was deleted\n"
                f"  expected SHA-256: {sha256.lower()}\n"
                f"  actual SHA-256:   {actual}"
            )
        partial.replace(target)
    except OSError as error:
        raise FetchError(f"could not save {target}: {error}") from error
    finally:
        partial.unlink(missing_ok=True)


def _file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    except OSError:
        return None


class Installer:
    """PawnIO's installer as temperature-tools.json pins it."""

    def __init__(self, name: str, url: str, sha256: str) -> None:
        self.name, self.url, self.sha256 = name, url, sha256.lower()


class Library:
    """One NuGet package and the one DLL taken from it."""

    def __init__(self, id: str, version: str, sha256: str, dll: str, dll_sha256: str) -> None:
        self.id, self.version, self.dll = id, version, dll
        self.sha256, self.dll_sha256 = sha256.lower(), dll_sha256.lower()
        self.name = dll.rsplit("/", 1)[-1]

    @property
    def url(self) -> str:
        return NUGET_URL.format(id=self.id, version=self.version)


def temperature_pins(folder: Path) -> tuple[Installer, list[Library]] | None:
    """The installer and libraries temperature-tools.json pins, or None if the
    file is missing or anything in it is not what is expected: then nothing
    of the temperature kit is fetched or packed."""
    try:
        pins = json.loads((folder / TEMPERATURE_PINS).read_text(encoding="utf-8"))
        pawnio = pins["pawnio"]
        installer = Installer(str(pawnio["file"]), str(pawnio["url"]), str(pawnio["sha256"]))
        libraries = [
            Library(
                str(lib["id"]),
                str(lib["version"]),
                str(lib["sha256"]),
                str(lib["dll"]),
                str(lib["dll_sha256"]),
            )
            for lib in pins["libraries"]
        ]
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError):
        return None
    if not (
        _SAFE_NAME.fullmatch(installer.name)
        and installer.name.lower().endswith(".exe")
        and installer.url.lower().startswith("https://")
        and _SHA256.fullmatch(installer.sha256)
        and libraries
    ):
        return None
    for lib in libraries:
        parts = lib.dll.split("/")
        if not (
            _SAFE_PART.fullmatch(lib.id)
            and _SAFE_PART.fullmatch(lib.version)
            and all(_SAFE_PART.fullmatch(part) and ".." not in part for part in parts)
            and lib.name.lower().endswith(".dll")
            and _SHA256.fullmatch(lib.sha256)
            and _SHA256.fullmatch(lib.dll_sha256)
        ):
            return None
    # One DLL per name, or two packages would fight over one file.
    if len({lib.name.lower() for lib in libraries}) != len(libraries):
        return None
    return installer, libraries


def trusted_temperature_tools(folder: Path) -> list[Path]:
    """PawnIO's installer and every pinned DLL, if every one of them is in
    tools/ with its pinned SHA-256; otherwise none at all. Nothing else in
    tools/lhm/ is ever packed. The installer comes first, then the DLLs by name."""
    pinned = temperature_pins(folder)
    if pinned is None:
        return []
    installer, libraries = pinned
    tools = folder / "tools"
    wanted = [(tools / installer.name, installer.sha256)]
    wanted += sorted(
        ((tools / LIBRARY_FOLDER / lib.name, lib.dll_sha256) for lib in libraries),
        key=lambda pair: pair[0].name,
    )
    if all(_file_sha256(path) == sha256 for path, sha256 in wanted):
        return [path for path, _ in wanted]
    return []


def _dll_from_package(lib: Library, package: bytes) -> bytes:
    """The one DLL a NuGet package is pinned for, read from the package's bytes."""
    try:
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            try:
                entry = archive.getinfo(lib.dll)
            except KeyError:
                raise FetchError(f"{lib.id} {lib.version} does not contain {lib.dll}") from None
            if entry.file_size > MAX_DLL_BYTES:
                raise FetchError(f"{lib.dll} in {lib.id} is larger than {MAX_DLL_BYTES} bytes")
            return archive.read(entry)
    except (zipfile.BadZipFile, OSError, ValueError, RuntimeError) as error:
        raise FetchError(f"{lib.id} {lib.version} could not be read: {error}") from error


def fetch_temperature_tools(folder: Path) -> list[Path]:
    """Put PawnIO's installer in folder/tools and each pinned DLL in
    folder/tools/lhm, and return their paths.

    Files already there with their pinned SHA-256 are kept and not fetched
    again. Each NuGet package must have its pinned SHA-256 before anything is
    taken from it, and only the one DLL it is pinned for is taken, which must
    have its own pinned SHA-256 too. Nothing that fails a check is written.
    Raises FetchError when it cannot be done."""
    pinned = temperature_pins(folder)
    if pinned is None:
        raise FetchError(f"{folder / TEMPERATURE_PINS} is missing or does not pin the tools")
    installer, libraries = pinned
    tools = folder / "tools"
    target = tools / installer.name
    if _file_sha256(target) != installer.sha256:
        data = _download(installer.url, MAX_INSTALLER_BYTES)
        _save_verified(target, data, installer.sha256, "PawnIO installer")
    for lib in libraries:
        dll = tools / LIBRARY_FOLDER / lib.name
        if _file_sha256(dll) == lib.dll_sha256:
            continue
        package = _download(lib.url, MAX_NUPKG_BYTES)
        actual = hashlib.sha256(package).hexdigest()
        if actual != lib.sha256:
            raise FetchError(
                f"the downloaded package is not the pinned {lib.id} {lib.version}, "
                "so nothing was taken from it\n"
                f"  expected SHA-256: {lib.sha256}\n"
                f"  actual SHA-256:   {actual}"
            )
        _save_verified(dll, _dll_from_package(lib, package), lib.dll_sha256, lib.name)
    paths = trusted_temperature_tools(folder)
    if not paths:  # cannot happen unless the files changed under us
        raise FetchError("the temperature tools did not check out after fetching them")
    return paths


USAGE = """usage: collector_build.py [--require-presentmon] [--require-temperature-tools]
                          <collector folder> <output zip>
       collector_build.py fetch-presentmon <collector folder>
       collector_build.py fetch-temperature-tools <collector folder>
       collector_build.py fetch-tools <collector folder>   (both of the above)"""


def _is_collector_folder(folder: Path) -> bool:
    if (folder / "Collect-PCDoctor.ps1").is_file():
        return True
    print(f"{folder} is not the collector folder", file=sys.stderr)
    return False


def _fetch_presentmon_now(folder: Path) -> bool:
    try:
        target = fetch_presentmon(folder)
    except FetchError as error:
        print(f"PresentMon was not fetched: {error}", file=sys.stderr)
        return False
    print(f"{hashlib.sha256(target.read_bytes()).hexdigest()}  {target}")
    return True


def _fetch_temperature_tools_now(folder: Path) -> bool:
    try:
        paths = fetch_temperature_tools(folder)
    except FetchError as error:
        print(f"The temperature tools were not fetched: {error}", file=sys.stderr)
        return False
    for path in paths:
        print(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path}")
    return True


FETCHERS = {
    "fetch-presentmon": (_fetch_presentmon_now,),
    "fetch-temperature-tools": (_fetch_temperature_tools_now,),
    "fetch-tools": (_fetch_presentmon_now, _fetch_temperature_tools_now),
}


def _fetch_command(fetchers: tuple, args: list[str]) -> int:
    if len(args) != 1:
        print(USAGE, file=sys.stderr)
        return 2
    folder = Path(args[0])
    if not _is_collector_folder(folder):
        return 2
    # Every one is tried, even after another failed.
    results = [fetch(folder) for fetch in fetchers]
    return 0 if all(results) else 1


def _missing_for_release(folder: Path, presentmon: bool, temperature: bool) -> list[str]:
    missing = []
    if presentmon:
        if not trusted_tools(folder):
            missing.append("the pinned PresentMon in tools/ (run: fetch-presentmon)")
        if not (folder / "PresentMon-LICENSE.txt").is_file():
            missing.append("PresentMon-LICENSE.txt")
    if temperature:
        if not trusted_temperature_tools(folder):
            missing.append(
                "the pinned temperature tools in tools/ (PawnIO_setup.exe and every "
                "DLL in tools/lhm/; run: fetch-temperature-tools)"
            )
        missing += [
            f"{LICENCES}/{name}"
            for name in TEMPERATURE_LICENCES
            if not (folder / LICENCES / name).is_file()
        ]
    return missing


def main(argv: list[str]) -> int:
    args = argv[1:]
    if args[:1] and args[0] in FETCHERS:
        return _fetch_command(FETCHERS[args[0]], args[1:])
    # A release must not quietly go out without PresentMon or the temperature
    # tools: with these flags a zip that would lack them is an error, and
    # nothing is written.
    require_presentmon = "--require-presentmon" in args
    require_temperature = "--require-temperature-tools" in args
    args = [a for a in args if a not in ("--require-presentmon", "--require-temperature-tools")]
    if len(args) != 2 or any(arg.startswith("--") for arg in args):
        print(USAGE, file=sys.stderr)
        return 2
    folder, out = Path(args[0]), Path(args[1])
    if not _is_collector_folder(folder):
        return 2
    missing = _missing_for_release(folder, require_presentmon, require_temperature)
    if missing:
        print(
            f"{folder} lacks "
            + "; ".join(missing)
            + f". Run: collector_build.py fetch-tools {folder}",
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
