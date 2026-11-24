"""The temperature tools in the collector zip: PawnIO's installer and
LibreHardwareMonitorLib with its libraries, all pinned in
collector/temperature-tools.json. Small fakes stand in for the real files."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import zipfile

import pytest

from pcdoctor_api.services import collector_build

from .test_intake import PINNED, PRESENTMON, collector_copy

INSTALLER = b"the PawnIO installer the pins name"
# (package id, version, path of the DLL inside the package, DLL bytes)
LIBRARIES = [
    ("librehardwaremonitorlib", "0.9.6", "runtimes/win-x64/lib/net472/LibreHardwareMonitorLib.dll"),
    ("hidsharp", "2.6.4", "lib/netstandard2.0/HidSharp.dll"),
    ("system.memory", "4.6.3", "lib/net462/System.Memory.dll"),
]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def dll_bytes(name: str) -> bytes:
    return f"MZ fake {name}".encode()


def nupkg(dll_path: str, dll: bytes | None) -> bytes:
    """A NuGet package (a zip) holding dll at dll_path, plus things that must stay behind."""
    buffer = io.BytesIO()
    entries = {"package.nuspec": b"<package/>", "lib/net8.0/Other.dll": b"not for .NET Framework"}
    if dll is not None:
        entries[dll_path] = dll
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            # A fixed date, so the same fake package always has the same hash.
            archive.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), data)
    return buffer.getvalue()


PACKAGES = {
    f"https://api.nuget.org/v3-flatcontainer/{i}/{v}/{i}.{v}.nupkg": nupkg(p, dll_bytes(p))
    for i, v, p in LIBRARIES
}
INSTALLER_URL = "https://github.com/namazso/PawnIO.Setup/releases/download/2.2.0/PawnIO_setup.exe"
DLL_NAMES = sorted(p.rsplit("/", 1)[-1] for _, _, p in LIBRARIES)


def temperature_folder(tmp_path):
    """A collector copy whose temperature-tools.json pins the fakes above."""
    folder = collector_copy(tmp_path, PINNED)
    pins = json.loads((folder / "temperature-tools.json").read_text(encoding="utf-8"))
    pins["pawnio"].update(url=INSTALLER_URL, sha256=sha(INSTALLER))
    pins["libraries"] = [
        {
            "id": i,
            "version": v,
            "sha256": sha(nupkg(p, dll_bytes(p))),
            "dll": p,
            "dll_sha256": sha(dll_bytes(p)),
        }
        for i, v, p in LIBRARIES
    ]
    (folder / "temperature-tools.json").write_text(json.dumps(pins, indent=2), encoding="utf-8")
    return folder


def put_tools(folder) -> None:
    """The verified files, where fetch-temperature-tools puts them."""
    (folder / "tools" / "lhm").mkdir(parents=True, exist_ok=True)
    (folder / "tools" / "PawnIO_setup.exe").write_bytes(INSTALLER)
    for _, _, path in LIBRARIES:
        (folder / "tools" / "lhm" / path.rsplit("/", 1)[-1]).write_bytes(dll_bytes(path))


def temperature_entries(data: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return [
            n for n in archive.namelist() if n.endswith("PawnIO_setup.exe") or "/tools/lhm/" in n
        ]


EXPECTED = ["PCDoctor-collector/tools/PawnIO_setup.exe"] + [
    f"PCDoctor-collector/tools/lhm/{name}" for name in DLL_NAMES
]


def test_the_real_pins_are_complete_and_well_formed():
    from pathlib import Path

    folder = Path(__file__).resolve().parents[2] / "collector"
    pinned = collector_build.temperature_pins(folder)
    assert pinned is not None
    installer, libraries = pinned
    assert installer.name == "PawnIO_setup.exe"
    assert len(libraries) == 14
    assert any(lib.name == "LibreHardwareMonitorLib.dll" for lib in libraries)
    for name in collector_build.TEMPERATURE_LICENCES:
        assert (folder / "licences" / name).is_file(), name
    listing = (folder / "licences" / "LIBRARIES.txt").read_text(encoding="ascii")
    for lib in libraries:
        assert lib.name in listing and lib.version in listing


def test_verified_temperature_tools_and_licences_are_packed(client, monkeypatch, tmp_path):
    from pcdoctor_api.config import get_settings

    folder = temperature_folder(tmp_path)
    put_tools(folder)
    # Anything else in tools/lhm stays behind.
    (folder / "tools" / "lhm" / "Planted.dll").write_bytes(b"planted")
    (folder / "tools" / "PawnIO_setup-old.exe").write_bytes(INSTALLER)
    monkeypatch.setenv("PCDOCTOR_COLLECTOR_DIR", str(folder))
    get_settings.cache_clear()

    data = client.get("/api/collector.zip").content
    assert temperature_entries(data) == EXPECTED
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        assert archive.read("PCDoctor-collector/tools/PawnIO_setup.exe") == INSTALLER
        for _, _, path in LIBRARIES:
            name = path.rsplit("/", 1)[-1]
            assert archive.read(f"PCDoctor-collector/tools/lhm/{name}") == dll_bytes(path)
        assert "PCDoctor-collector/temperature-tools.json" in names
        for name in collector_build.TEMPERATURE_LICENCES:
            assert f"PCDoctor-collector/licences/{name}" in names
        gpl = archive.read("PCDoctor-collector/licences/PawnIO-COPYING.txt").decode()
        assert "GNU GENERAL PUBLIC LICENSE" in gpl and "Version 2" in gpl
        assert (
            "Mozilla Public License"
            in archive.read("PCDoctor-collector/licences/MPL-2.0.txt").decode()
        )
        assert not [n for n in names if "Planted" in n or "setup-old" in n]
    info = client.get("/api/collector").json()
    assert info["includes_temperature_tools"] is True
    assert info["includes_presentmon"] is False


@pytest.mark.parametrize(
    "spoil",
    [
        lambda f: (f / "tools" / "PawnIO_setup.exe").write_bytes(b"swapped installer"),
        lambda f: (f / "tools" / "PawnIO_setup.exe").unlink(),
        lambda f: (f / "tools" / "lhm" / "HidSharp.dll").write_bytes(b"swapped dll"),
        lambda f: (f / "tools" / "lhm" / "System.Memory.dll").unlink(),
        lambda f: (f / "temperature-tools.json").write_text("{not json", encoding="utf-8"),
    ],
    ids=["wrong installer", "no installer", "wrong dll", "missing dll", "broken pins"],
)
def test_one_wrong_file_means_none_of_the_temperature_tools_are_packed(
    client, monkeypatch, tmp_path, spoil
):
    from pcdoctor_api.config import get_settings

    folder = temperature_folder(tmp_path)
    put_tools(folder)
    (folder / "tools" / PRESENTMON).write_bytes(PINNED)
    spoil(folder)
    monkeypatch.setenv("PCDOCTOR_COLLECTOR_DIR", str(folder))
    get_settings.cache_clear()

    data = client.get("/api/collector.zip").content
    assert temperature_entries(data) == []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        # The rest of the zip is untouched: PresentMon and the licences still go.
        assert f"PCDoctor-collector/tools/{PRESENTMON}" in archive.namelist()
        assert "PCDoctor-collector/licences/PawnIO-COPYING.txt" in archive.namelist()
    assert client.get("/api/collector").json()["includes_temperature_tools"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"dll": "../../outside.dll"},
        {"dll": "lib/net472/Not-a-library.exe"},
        {"id": "a/b"},
        {"dll_sha256": "abc"},
    ],
)
def test_pins_that_could_escape_or_are_malformed_are_refused(tmp_path, change):
    folder = temperature_folder(tmp_path)
    put_tools(folder)
    pins = json.loads((folder / "temperature-tools.json").read_text(encoding="utf-8"))
    pins["libraries"][0].update(change)
    (folder / "temperature-tools.json").write_text(json.dumps(pins), encoding="utf-8")
    assert collector_build.temperature_pins(folder) is None
    assert collector_build.trusted_temperature_tools(folder) == []
    with pytest.raises(collector_build.FetchError):
        collector_build.fetch_temperature_tools(folder)


def test_the_zip_with_temperature_tools_is_the_same_bytes_every_time(tmp_path):
    folder = temperature_folder(tmp_path)
    without = collector_build.collector_zip(folder)
    put_tools(folder)
    (folder / "tools" / PRESENTMON).write_bytes(PINNED)
    first = collector_build.collector_zip(folder)
    assert first != without
    for path in (folder / "tools").rglob("*"):
        os.utime(path, (1_000_000_000, 1_000_000_000))
    moved = tmp_path / "elsewhere"
    shutil.copytree(folder, moved)
    assert collector_build.collector_zip(folder) == first
    assert collector_build.collector_zip(moved) == first
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        names = archive.namelist()
        assert all(archive.getinfo(n).date_time == collector_build.FIXED_TIME for n in names)
        # Scripts, licences, PresentMon, then the temperature kit, in a fixed order.
        assert names[-len(EXPECTED) :] == EXPECTED
        assert names[-len(EXPECTED) - 1] == f"PCDoctor-collector/tools/{PRESENTMON}"
        licences = [n for n in names if "/licences/" in n]
        assert licences == sorted(licences)
        assert names.index(licences[-1]) < names.index(f"PCDoctor-collector/tools/{PRESENTMON}")


class FakeNet:
    """Stands in for _download: serves the given bodies and records what was asked."""

    def __init__(self, bodies: dict[str, bytes]) -> None:
        self.bodies, self.asked = dict(bodies), []

    def __call__(self, url: str, limit: int) -> bytes:
        self.asked.append(url)
        if url not in self.bodies:
            raise collector_build.FetchError(f"download failed: no {url}")
        return self.bodies[url]


def test_fetching_the_temperature_tools_keeps_only_verified_files(tmp_path, monkeypatch, capsys):
    folder = temperature_folder(tmp_path)
    net = FakeNet({INSTALLER_URL: INSTALLER, **PACKAGES})
    monkeypatch.setattr(collector_build, "_download", net)

    assert collector_build.main(["build", "fetch-temperature-tools", str(folder)]) == 0
    assert sorted(net.asked) == sorted([INSTALLER_URL, *PACKAGES])
    assert (folder / "tools" / "PawnIO_setup.exe").read_bytes() == INSTALLER
    # Only the named DLL is taken from each package, under its own name.
    assert sorted(p.name for p in (folder / "tools" / "lhm").iterdir()) == DLL_NAMES
    assert len(collector_build.trusted_temperature_tools(folder)) == 1 + len(LIBRARIES)

    # Already there and correct: no download at all.
    net.asked.clear()
    assert collector_build.main(["build", "fetch-temperature-tools", str(folder)]) == 0
    assert net.asked == []

    # One swapped DLL: only its package is fetched again.
    (folder / "tools" / "lhm" / "HidSharp.dll").write_bytes(b"swapped")
    collector_build.fetch_temperature_tools(folder)
    assert net.asked == [u for u in PACKAGES if "/hidsharp/" in u]
    assert len(collector_build.trusted_temperature_tools(folder)) == 1 + len(LIBRARIES)
    capsys.readouterr()


def test_a_package_with_the_wrong_hash_gives_nothing(tmp_path, monkeypatch, capsys):
    folder = temperature_folder(tmp_path)
    url = next(u for u in PACKAGES if "/hidsharp/" in u)
    # A different package that does contain a DLL with the pinned bytes: the
    # package's own hash is checked first, so nothing is taken from it.
    planted = nupkg("lib/netstandard2.0/HidSharp.dll", dll_bytes("lib/netstandard2.0/HidSharp.dll"))
    planted += b"\0"
    monkeypatch.setattr(
        collector_build, "_download", FakeNet({INSTALLER_URL: INSTALLER, **PACKAGES, url: planted})
    )
    assert collector_build.main(["build", "fetch-temperature-tools", str(folder)]) == 1
    err = capsys.readouterr().err
    assert "not the pinned hidsharp 2.6.4" in err
    assert not (folder / "tools" / "lhm" / "HidSharp.dll").exists()
    assert not list((folder / "tools").rglob("*.download"))
    assert collector_build.trusted_temperature_tools(folder) == []
    assert temperature_entries(collector_build.collector_zip(folder)) == []


def test_a_package_without_its_dll_or_with_a_wrong_dll_gives_nothing(tmp_path, monkeypatch):
    folder = temperature_folder(tmp_path)
    pins = json.loads((folder / "temperature-tools.json").read_text(encoding="utf-8"))
    hid = next(lib for lib in pins["libraries"] if lib["id"] == "hidsharp")
    url = next(u for u in PACKAGES if "/hidsharp/" in u)

    # The package is the pinned one but lacks the DLL.
    empty = nupkg(hid["dll"], None)
    hid["sha256"] = sha(empty)
    (folder / "temperature-tools.json").write_text(json.dumps(pins), encoding="utf-8")
    monkeypatch.setattr(
        collector_build, "_download", FakeNet({INSTALLER_URL: INSTALLER, **PACKAGES, url: empty})
    )
    with pytest.raises(collector_build.FetchError, match="does not contain"):
        collector_build.fetch_temperature_tools(folder)
    assert not (folder / "tools" / "lhm" / "HidSharp.dll").exists()

    # The package is the pinned one, but its DLL is not the pinned DLL.
    other = nupkg(hid["dll"], b"MZ some other build")
    hid["sha256"] = sha(other)
    (folder / "temperature-tools.json").write_text(json.dumps(pins), encoding="utf-8")
    monkeypatch.setattr(
        collector_build, "_download", FakeNet({INSTALLER_URL: INSTALLER, **PACKAGES, url: other})
    )
    with pytest.raises(collector_build.FetchError, match="not the pinned HidSharp.dll"):
        collector_build.fetch_temperature_tools(folder)
    assert not (folder / "tools" / "lhm" / "HidSharp.dll").exists()
    assert not list((folder / "tools").rglob("*.download"))

    # Not a zip at all.
    hid["sha256"] = sha(b"garbage")
    (folder / "temperature-tools.json").write_text(json.dumps(pins), encoding="utf-8")
    monkeypatch.setattr(
        collector_build,
        "_download",
        FakeNet({INSTALLER_URL: INSTALLER, **PACKAGES, url: b"garbage"}),
    )
    with pytest.raises(collector_build.FetchError, match="could not be read"):
        collector_build.fetch_temperature_tools(folder)
    assert collector_build.trusted_temperature_tools(folder) == []


def test_a_wrong_installer_is_not_kept(tmp_path, monkeypatch):
    folder = temperature_folder(tmp_path)
    monkeypatch.setattr(collector_build, "_download", FakeNet({INSTALLER_URL: b"evil", **PACKAGES}))
    with pytest.raises(collector_build.FetchError, match="not the pinned PawnIO installer"):
        collector_build.fetch_temperature_tools(folder)
    assert not (folder / "tools" / "PawnIO_setup.exe").exists()
    assert not list((folder / "tools").rglob("*.download"))


def test_fetch_tools_fetches_both_and_reports_either_failure(tmp_path, monkeypatch, capsys):
    folder = temperature_folder(tmp_path)
    presentmon_url = (
        "https://github.com/GameTechDev/PresentMon/releases/download/v2.6.0/" + PRESENTMON
    )
    # PresentMon fails, the temperature tools are still fetched.
    net = FakeNet({INSTALLER_URL: INSTALLER, **PACKAGES})
    monkeypatch.setattr(collector_build, "_download", net)
    assert collector_build.main(["build", "fetch-tools", str(folder)]) == 1
    assert "PresentMon was not fetched" in capsys.readouterr().err
    assert collector_build.trusted_temperature_tools(folder)

    net.bodies[presentmon_url] = PINNED
    assert collector_build.main(["build", "fetch-tools", str(folder)]) == 0
    assert collector_build.trusted_tools(folder)
    assert collector_build.main(["build", "fetch-tools"]) == 2
    assert (
        collector_build.main(["build", "fetch-temperature-tools", str(tmp_path / "nowhere")]) == 2
    )


def test_a_release_build_refuses_to_go_out_without_the_temperature_tools(tmp_path, capsys):
    folder = temperature_folder(tmp_path)
    out = tmp_path / "dist" / "PCDoctor-collector.zip"
    both = ["--require-presentmon", "--require-temperature-tools"]
    (folder / "tools").mkdir()
    (folder / "tools" / PRESENTMON).write_bytes(PINNED)

    assert (
        collector_build.main(["build", "--require-temperature-tools", str(folder), str(out)]) == 1
    )
    assert not out.exists()
    assert "fetch-temperature-tools" in capsys.readouterr().err
    # PresentMon alone is still enough for --require-presentmon.
    assert collector_build.main(["build", "--require-presentmon", str(folder), str(out)]) == 0
    out.unlink()

    put_tools(folder)
    (folder / "tools" / "lhm" / "HidSharp.dll").write_bytes(b"swapped")
    assert collector_build.main(["build", *both, str(folder), str(out)]) == 1
    assert not out.exists()

    put_tools(folder)
    assert collector_build.main(["build", *both, str(folder), str(out)]) == 0
    assert out.read_bytes() == collector_build.collector_zip(folder)
    assert temperature_entries(out.read_bytes()) == EXPECTED
    out.unlink()

    # The licences must travel with the programs.
    (folder / "licences" / "PawnIO-COPYING.txt").unlink()
    assert (
        collector_build.main(["build", str(folder), str(out), "--require-temperature-tools"]) == 1
    )
    assert "licences/PawnIO-COPYING.txt" in capsys.readouterr().err
    assert not out.exists()
