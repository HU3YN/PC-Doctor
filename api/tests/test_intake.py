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
