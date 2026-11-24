from __future__ import annotations

import io
import zipfile

import pytest

from pcdoctor_api.services import photo

from .conftest import entry

needs_ocr = pytest.mark.skipif(not photo.available(), reason="Tesseract is not installed")


def blue_screen(lines: list[str]) -> bytes:
    """A picture of a blue screen, drawn the way Windows draws one."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1280, 720), (0, 120, 215))
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 30)
    except OSError:
        font = ImageFont.load_default(size=30)
    for number, line in enumerate(lines):
        draw.text((90, 150 + number * 52), line, fill="white", font=font)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def send(client, data: bytes, name: str = "photo.png"):
    return client.post("/api/photos", files={"file": (name, data, "image/png")})


def test_collector_download_is_a_ready_to_use_zip(client):
    info = client.get("/api/collector").json()
    assert info["available"] is True and isinstance(info["lan_addresses"], list)
    response = client.get("/api/collector.zip")
    assert response.status_code == 200
    assert "PCDoctor-collector.zip" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert {
            "PCDoctor-collector/PCDoctor.cmd",
            "PCDoctor-collector/Collect-PCDoctor.ps1",
            "PCDoctor-collector/PCDoctorCollector.psm1",
        } <= names
        assert not any("tests" in name for name in names)
        launcher = archive.read("PCDoctor-collector/PCDoctor.cmd")
        assert b"\r\n" in launcher and b"\n" not in launcher.replace(b"\r\n", b"")  # CRLF only


def test_collector_download_is_404_when_the_collector_is_not_there(client, monkeypatch, tmp_path):
    from pcdoctor_api.config import get_settings

    monkeypatch.setenv("PCDOCTOR_COLLECTOR_DIR", str(tmp_path))
    get_settings.cache_clear()
    assert client.get("/api/collector").json()["available"] is False
    assert client.get("/api/collector.zip").status_code == 404


def test_no_boot_guide(client):
    guide = client.get("/api/noboot").json()
    assert len(guide) >= 10
    dram = next(item for item in guide if item["key"] == "led_dram")
    assert dram["category"] == "memory" and len(dram["checks"]) >= 3


@needs_ocr
def test_photo_of_a_blue_screen_is_read_and_matched_to_an_earlier_job(client):
    client.post("/api/worklog", json=entry(title="Bad SSD", error_codes=["0xEF"], status="fixed"))
    result = send(
        client,
        blue_screen(
            [
                "Your PC ran into a problem and needs to restart.",
                "We're just collecting some error info.",
                "Stop code: CRITICAL_PROCESS_DIED",
            ]
        ),
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["is_blue_screen"] is True
    assert [code["hex"] for code in body["stop_codes"]] == ["0xEF"]
    assert body["stop_codes"][0]["checks"]
    assert [case["entry"]["title"] for case in body["cases"]] == ["Bad SSD"]


@needs_ocr
def test_photo_with_a_hex_code_and_a_driver_name(client):
    body = send(
        client,
        blue_screen(
            [
                "A problem has been detected and Windows has been shut down.",
                "*** STOP: 0x00000116 (0xFFFFFA80, 0xFFFFF880)",
                "*** nvlddmkm.sys - Address FFFFF880",
            ]
        ),
    ).json()
    assert [code["name"] for code in body["stop_codes"]] == ["VIDEO_TDR_FAILURE"]
    assert "nvlddmkm.sys" in body["drivers"]


@needs_ocr
def test_photo_with_no_error_on_it_finds_nothing_and_does_not_guess(client):
    body = send(client, blue_screen(["Press F1 to run setup", "Press F2 to load defaults"])).json()
    assert body["stop_codes"] == [] and body["cases"] == [] and body["is_blue_screen"] is False


@needs_ocr
def test_bad_photo_uploads_get_a_clear_error_and_nothing_is_stored(client, tmp_path):
    assert send(client, b"").status_code == 400
    response = send(client, b"this is not an image")
    assert response.status_code == 400 and "not a photo" in response.json()["detail"]
    from pcdoctor_api.config import get_settings

    stored = [p for p in get_settings().data_dir.rglob("*") if p.suffix in (".png", ".jpg")]
    assert stored == []


def test_photo_reading_says_so_when_tesseract_is_missing(client, monkeypatch):
    def unavailable():
        raise photo.OcrUnavailable("Photo reading needs the Tesseract OCR program")

    monkeypatch.setattr(photo, "_engine", unavailable)
    response = send(client, b"anything")
    assert response.status_code == 503 and "Tesseract" in response.json()["detail"]
    assert client.get("/api/collector").json()["photo_reading"] is False


def framed(picture: bytes, border: int, tilt: float = 0.0) -> bytes:
    """The screen as a phone sees it: a dark bezel around it, maybe a little tilted."""
    from PIL import Image

    screen = Image.open(io.BytesIO(picture)).convert("RGB")
    photo_image = Image.new(
        "RGB", (screen.width + 2 * border, screen.height + 2 * border), (18, 18, 20)
    )
    photo_image.paste(screen, (border, border))
    if tilt:
        photo_image = photo_image.rotate(tilt, expand=True, fillcolor=(0, 0, 0))
    buffer = io.BytesIO()
    photo_image.save(buffer, "JPEG", quality=88)
    return buffer.getvalue()


@needs_ocr
@pytest.mark.parametrize(("border", "tilt"), [(20, 0.0), (200, 0.0), (0, 2.0), (80, -2.0)])
def test_a_bezel_or_a_tilt_does_not_hide_the_stop_code(border, tilt):
    # Regression: a dark border or a 2-degree tilt used to make the reader
    # return no text at all (found by eval/photo_eval.py).
    from pcdoctor_analysis import errortext

    picture = blue_screen(
        ["Your PC ran into a problem and needs to restart.", "Stop code: CRITICAL_PROCESS_DIED"]
    )
    text = photo.read_text(framed(picture, border, tilt))
    found = errortext.interpret(text)
    assert "CRITICAL_PROCESS_DIED" in str(found), text


def collector_copy(tmp_path, pinned_file: bytes | None = None):
    """A copy of the real collector folder, without tools/. With pinned_file,
    its Get-Tools.ps1 pins that file's SHA-256 instead of the real PresentMon's,
    so tests can stand in a small fake for Intel's program."""
    import hashlib
    import re
    import shutil
    from pathlib import Path

    source = Path(__file__).resolve().parents[2] / "collector"
    folder = tmp_path / "collector"
    shutil.copytree(source, folder, ignore=shutil.ignore_patterns("tools", "runs", "tests"))
    if pinned_file is not None:
        script = folder / "Get-Tools.ps1"
        text, changed = re.subn(
            r"\$Sha256 = '[0-9A-F]{64}'",
            f"$Sha256 = '{hashlib.sha256(pinned_file).hexdigest().upper()}'",
            script.read_text(encoding="utf-8"),
        )
        assert changed == 1
        script.write_text(text, encoding="utf-8")
    return folder


PINNED = b"the file Get-Tools.ps1 pins"
PRESENTMON = "PresentMon-2.6.0-x64.exe"


def test_only_the_pinned_presentmon_is_shipped_with_the_collector(client, monkeypatch, tmp_path):
    from pcdoctor_api.config import get_settings

    folder = collector_copy(tmp_path, PINNED)
    (folder / "tools").mkdir()
    (folder / "tools" / PRESENTMON).write_bytes(PINNED)
    (folder / "tools" / "PresentMon-9.9.9-x64.exe").write_bytes(b"planted")
    # The right bytes under another name stay behind too: one commit, one zip.
    (folder / "tools" / "PresentMon-copy.exe").write_bytes(PINNED)
    (folder / "tools" / "notes.txt").write_bytes(b"left by someone")
    monkeypatch.setenv("PCDOCTOR_COLLECTOR_DIR", str(folder))
    get_settings.cache_clear()

    # One download has everything: the scripts, PresentMon, and Intel's licence.
    with zipfile.ZipFile(io.BytesIO(client.get("/api/collector.zip").content)) as archive:
        names = archive.namelist()
        assert [n for n in names if "/tools/" in n] == [f"PCDoctor-collector/tools/{PRESENTMON}"]
        assert archive.read(f"PCDoctor-collector/tools/{PRESENTMON}") == PINNED
        assert "PCDoctor-collector/PCDoctor.cmd" in names
        licence = archive.read("PCDoctor-collector/PresentMon-LICENSE.txt").decode()
        assert "Intel Corporation" in licence
        assert "Permission is hereby granted, free of charge" in licence
    assert client.get("/api/collector").json()["includes_presentmon"] is True
    # The separate PresentMon download is gone.
    assert client.get("/api/collector/presentmon.zip").status_code == 404

    # A swapped file is never packed, and the page is told so.
    (folder / "tools" / PRESENTMON).write_bytes(b"swapped")
    with zipfile.ZipFile(io.BytesIO(client.get("/api/collector.zip").content)) as archive:
        assert not [n for n in archive.namelist() if "/tools/" in n]
        assert "PCDoctor-collector/PresentMon-LICENSE.txt" in archive.namelist()
    assert client.get("/api/collector").json()["includes_presentmon"] is False


def test_the_zip_with_presentmon_is_the_same_bytes_every_time(tmp_path):
    import os
    import shutil

    from pcdoctor_api.services import collector_build

    folder = collector_copy(tmp_path, PINNED)
    without = collector_build.collector_zip(folder)
    (folder / "tools").mkdir()
    (folder / "tools" / PRESENTMON).write_bytes(PINNED)
    first = collector_build.collector_zip(folder)
    assert first != without
    # Neither the file's date nor where the folder is changes the bytes.
    os.utime(folder / "tools" / PRESENTMON, (1_000_000_000, 1_000_000_000))
    moved = tmp_path / "elsewhere"
    shutil.copytree(folder, moved)
    assert collector_build.collector_zip(folder) == first
    assert collector_build.collector_zip(moved) == first
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        entry = archive.getinfo(f"PCDoctor-collector/tools/{PRESENTMON}")
        assert entry.date_time == collector_build.FIXED_TIME
        # PresentMon comes after the scripts, in a fixed place.
        assert archive.namelist()[-1] == entry.filename


def test_a_release_build_refuses_to_go_out_without_presentmon(tmp_path, capsys):
    from pcdoctor_api.services import collector_build

    folder = collector_copy(tmp_path, PINNED)
    out = tmp_path / "dist" / "PCDoctor-collector.zip"
    assert collector_build.main(["build", "--require-presentmon", str(folder), str(out)]) == 1
    assert not out.exists()
    assert "fetch-presentmon" in capsys.readouterr().err
    # A file that is not the pinned one does not count.
    (folder / "tools").mkdir()
    (folder / "tools" / PRESENTMON).write_bytes(b"swapped")
    assert collector_build.main(["build", str(folder), str(out), "--require-presentmon"]) == 1
    assert not out.exists()
    # Without the flag the scripts-only zip still builds.
    assert collector_build.main(["build", str(folder), str(out)]) == 0
    out.unlink()

    (folder / "tools" / PRESENTMON).write_bytes(PINNED)
    assert collector_build.main(["build", "--require-presentmon", str(folder), str(out)]) == 0
    assert out.read_bytes() == collector_build.collector_zip(folder)
    with zipfile.ZipFile(out) as archive:
        assert f"PCDoctor-collector/tools/{PRESENTMON}" in archive.namelist()
    # Intel's licence has to travel with their program.
    (folder / "PresentMon-LICENSE.txt").unlink()
    assert collector_build.main(["build", "--require-presentmon", str(folder), str(out)]) == 1

    assert collector_build.main(["build"]) == 2
    assert collector_build.main(["build", "--no-such-flag", str(folder), str(out)]) == 2
    assert collector_build.main(["build", str(tmp_path / "nowhere"), str(out)]) == 2


def test_fetching_presentmon_keeps_only_the_pinned_file(tmp_path, monkeypatch, capsys):
    from pcdoctor_api.services import collector_build

    folder = collector_copy(tmp_path, PINNED)
    target = folder / "tools" / PRESENTMON
    asked: list[str] = []

    def download(body: bytes):
        def fake(url: str, limit: int) -> bytes:
            asked.append(url)
            return body

        return fake

    # The wrong bytes: an error, and nothing is left behind.
    monkeypatch.setattr(collector_build, "_download", download(b"something else"))
    assert collector_build.main(["build", "fetch-presentmon", str(folder)]) == 1
    assert "not the pinned PresentMon" in capsys.readouterr().err
    assert list((folder / "tools").iterdir()) == []
    assert asked == [
        "https://github.com/GameTechDev/PresentMon/releases/download/v2.6.0/" + PRESENTMON
    ]

    # The pinned bytes are saved under the name the collector looks for.
    monkeypatch.setattr(collector_build, "_download", download(PINNED))
    assert collector_build.main(["build", "fetch-presentmon", str(folder)]) == 0
    assert target.read_bytes() == PINNED
    assert [path.name for path in (folder / "tools").iterdir()] == [PRESENTMON]
    assert collector_build.trusted_tools(folder) == [target]

    # Already there and correct: no download at all.
    def must_not_run(url: str, limit: int) -> bytes:
        raise AssertionError("downloaded again")

    monkeypatch.setattr(collector_build, "_download", must_not_run)
    assert collector_build.main(["build", "fetch-presentmon", str(folder)]) == 0

    # A swapped file is replaced by the pinned one.
    target.write_bytes(b"swapped")
    monkeypatch.setattr(collector_build, "_download", download(PINNED))
    assert collector_build.fetch_presentmon(folder) == target
    assert target.read_bytes() == PINNED

    assert collector_build.main(["build", "fetch-presentmon"]) == 2
    assert collector_build.main(["build", "fetch-presentmon", str(tmp_path / "nowhere")]) == 2


def test_fetching_presentmon_needs_a_pin_and_https(tmp_path, monkeypatch):
    import urllib.request

    from pcdoctor_api.services import collector_build

    folder = collector_copy(tmp_path, PINNED)

    # Plain http is refused before anything is sent...
    def no_network(*args, **kwargs):
        raise AssertionError("opened a connection")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", no_network)
    with pytest.raises(collector_build.FetchError, match="https"):
        collector_build._download("http://example.com/PresentMon.exe", 10)
    # ...and so is a redirect from https to anything else.
    with pytest.raises(collector_build.FetchError, match="redirect"):
        collector_build._HttpsOnly().redirect_request(
            urllib.request.Request("https://example.com/a"), None, 302, "Found", {}, "http://x/a"
        )

    # A reply bigger than the cap is not PresentMon.
    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", lambda *a, **k: Reply(b"x" * 11))
    with pytest.raises(collector_build.FetchError, match="larger"):
        collector_build._download("https://example.com/PresentMon.exe", 10)
    assert collector_build._download("https://example.com/PresentMon.exe", 11) == b"x" * 11

    # Without a pinned hash there is nothing to check a download against.
    (folder / "Get-Tools.ps1").write_text("[string]$Version = '2.6.0'\n", encoding="utf-8")
    monkeypatch.setattr(collector_build, "_download", no_network)
    with pytest.raises(collector_build.FetchError, match="pin"):
        collector_build.fetch_presentmon(folder)
    assert collector_build.trusted_tools(folder) == []


def test_the_collector_zip_is_the_same_bytes_every_time(client, tmp_path):
    import hashlib
    import shutil
    import time
    from pathlib import Path

    from pcdoctor_api.services import collector_build

    source = Path(__file__).resolve().parents[2] / "collector"
    first = client.get("/api/collector.zip").content
    time.sleep(1.1)  # a zip that stored the time would differ now
    assert client.get("/api/collector.zip").content == first
    assert client.get("/api/collector").json()["sha256"] == hashlib.sha256(first).hexdigest()
    # The same files with Windows line endings (a checkout on Windows) give the same bytes.
    crlf = tmp_path / "crlf"
    shutil.copytree(source, crlf, ignore=shutil.ignore_patterns("runs", "tests"))
    for path in crlf.iterdir():
        if path.is_file():
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert collector_build.collector_zip(crlf) == first
    # And the command-line build the release workflow runs writes them too.
    out = tmp_path / "dist" / "PCDoctor-collector.zip"
    assert collector_build.main(["build", str(source), str(out)]) == 0
    assert out.read_bytes() == first


def test_only_jpeg_png_and_webp_are_decoded():
    from PIL import Image

    def encoded(kind: str, size=(64, 48)) -> bytes:
        buffer = io.BytesIO()
        Image.new("RGB", size, (0, 120, 215)).save(buffer, kind)
        return buffer.getvalue()

    for kind in ("JPEG", "PNG", "WEBP"):
        assert photo.open_photo(encoded(kind)).size == (64, 48)
    for kind in ("GIF", "BMP", "TIFF", "PPM"):
        with pytest.raises(photo.PhotoError):
            photo.open_photo(encoded(kind))


def test_an_image_over_the_pixel_limit_is_refused_and_nothing_global_changes(monkeypatch):
    from PIL import Image

    before = Image.MAX_IMAGE_PIXELS
    buffer = io.BytesIO()
    Image.new("L", (120, 100), 0).save(buffer, "PNG")  # 12,000 pixels
    # Between the limit and twice the limit, Pillow itself only warns.
    monkeypatch.setattr(photo, "MAX_PIXELS", 10_000)
    with pytest.raises(photo.PhotoError):
        photo.open_photo(buffer.getvalue())
    monkeypatch.setattr(photo, "MAX_PIXELS", 5_000)
    with pytest.raises(photo.PhotoError):
        photo.open_photo(buffer.getvalue())
    # Pillow's own process-wide limit is left as it was.
    assert before == Image.MAX_IMAGE_PIXELS
