"""Regression tests for bugs the fuzz tests in fuzz/test_fuzz_ingest.py found
in services/ingest.unpack (2026-11-14). See fuzz/README.md.

Every damaged or hostile upload must end in UploadError (shown to the user as
a 400), never in another exception (a 500), and must never write more than
max_unpacked_mb.
"""

from __future__ import annotations

import struct
import zlib

import pytest

from pcdoctor_api.config import Settings
from pcdoctor_api.services.ingest import UploadError, unpack

SETTINGS = Settings(max_unpacked_mb=1)


def one_entry_zip(
    name: bytes, data: bytes, *, method: int = 8, flags: int = 0, crc: int | None = None
) -> bytes:
    """A one-file zip built by hand, so the fields can lie."""
    if method == 8:
        packer = zlib.compressobj(9, zlib.DEFLATED, -15)
        packed = packer.compress(data) + packer.flush()
    else:
        packed = data
    crc = zlib.crc32(data) if crc is None else crc
    local = struct.pack(
        "<4sHHHHHIIIHH",
        b"PK\x03\x04",
        20,
        flags,
        method,
        0,
        0x21,
        crc,
        len(packed),
        len(data),
        len(name),
        0,
    )
    central = struct.pack(
        "<4sHHHHHHIIIHHHHHII",
        b"PK\x01\x02",
        20,
        20,
        flags,
        method,
        0,
        0x21,
        crc,
        len(packed),
        len(data),
        len(name),
        0,
        0,
        0,
        0,
        0,
        0,
    )
    body = local + name + packed
    end = struct.pack(
        "<4sHHHHIIH", b"PK\x05\x06", 0, 0, 1, 1, len(central) + len(name), len(body), 0
    )
    return body + central + name + end


def refused(data: bytes, tmp_path) -> UploadError:
    with pytest.raises(UploadError) as caught:
        unpack(data, tmp_path, SETTINGS)
    return caught.value


def test_name_that_is_not_utf8_is_refused(tmp_path):
    # Flag bit 11 says "the name is UTF-8", but it is not: zipfile raised
    # UnicodeDecodeError.
    data = one_entry_zip(b"\xff\xfe/collector.log", b"x", flags=0x800)
    refused(data, tmp_path)


def test_bad_crc_is_refused(tmp_path):
    # zipfile raised BadZipFile while reading, after unpack had checked the zip.
    data = one_entry_zip(b"collector.log", b"hello", crc=0)
    refused(data, tmp_path)


@pytest.mark.parametrize("method", [1, 12, 14, 99])
def test_unsupported_compression_is_refused(tmp_path, method):
    # Implode, bzip2, LZMA, AES with bytes that are not what they claim:
    # NotImplementedError or a decompressor error.
    refused(one_entry_zip(b"manifest.json", b"{}", method=method), tmp_path)


def test_corrupt_deflate_stream_is_refused(tmp_path):
    good = one_entry_zip(b"manifest.json", b"{}" * 100)
    start = 30 + len(b"manifest.json")
    broken = good[:start] + bytes([good[start] ^ 0xFF]) + good[start + 1 :]
    refused(broken, tmp_path)


def test_bare_csv_over_the_limit_is_refused(tmp_path):
    # The zip path counted bytes; the bare-CSV path wrote any size.
    data = b"Application,MsBetweenPresents\n" + b"1\n" * (1024 * 1024)
    error = refused(data, tmp_path)
    assert "over the limit" in str(error)
    assert list(tmp_path.iterdir()) == []


def test_encrypted_entry_is_refused(tmp_path):
    error = refused(one_entry_zip(b"manifest.json", b"{}", flags=0x1), tmp_path)
    assert "password" in str(error)
    assert list(tmp_path.iterdir()) == []
