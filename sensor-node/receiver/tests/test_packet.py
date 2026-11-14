"""The packet format: golden bytes, CRC, rejections, and agreement with the C
encoder the firmware actually uses."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from case_sensor import packet
from case_sensor.packet import PacketError, Reading, crc16, decode, encode

FIRMWARE_LIB = Path(__file__).resolve().parents[2] / "firmware" / "lib" / "pcd_protocol" / "src"

# The same bytes are hard-coded in firmware/test_host/test_protocol.cpp.
GOLDEN_READING = Reading(
    node_id=0xA1B2C3D4,
    seq=0x01020304,
    uptime_ms=12345678,
    temp_centi_c=2345,
    humidity_centi_pct=4567,
    flags=0x03,
)
GOLDEN = bytes.fromhex("50440103d4c3b2a1040302014e61bc002909d71110f2")
GOLDEN_NEGATIVE = bytes.fromhex("50440101d4c3b2a1040302014e61bc002efb00006b81")


def test_crc16_standard_check_value():
    assert crc16(b"123456789") == 0x29B1
    assert crc16(b"") == 0xFFFF


def test_encode_matches_golden_bytes():
    assert encode(GOLDEN_READING) == GOLDEN
    assert len(GOLDEN) == packet.PACKET_SIZE


def test_negative_temperature_matches_golden_bytes():
    reading = Reading(0xA1B2C3D4, 0x01020304, 12345678, -1234, 0, flags=packet.FLAG_TEMP_VALID)
    assert encode(reading) == GOLDEN_NEGATIVE
    assert decode(GOLDEN_NEGATIVE) == reading


def test_decode_golden():
    reading = decode(GOLDEN)
    assert reading == GOLDEN_READING
    assert reading.temp_c == 23.45
    assert reading.humidity_pct == 45.67


def test_invalid_flags_hide_the_value():
    reading = decode(GOLDEN_NEGATIVE)  # only the temperature flag is set
    assert reading.temp_c == -12.34
    assert reading.humidity_pct is None


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"", "length"),
        (GOLDEN[:-1], "length"),
        (GOLDEN + b"\x00", "length"),
        (b"Q" + GOLDEN[1:], "magic"),
        (GOLDEN[:2] + b"\x02" + GOLDEN[3:], "version"),
        (GOLDEN[:16] + b"\x2a" + GOLDEN[17:], "crc"),
    ],
)
def test_decode_rejects(data, reason):
    with pytest.raises(PacketError) as caught:
        decode(data)
    assert caught.value.reason == reason


def test_every_single_bit_flip_is_rejected():
    for bit in range(packet.PACKET_SIZE * 8):
        damaged = bytearray(GOLDEN)
        damaged[bit // 8] ^= 1 << (bit % 8)
        with pytest.raises(PacketError):
            decode(bytes(damaged))


# ---- Agreement with the firmware's C code --------------------------------

# A tiny C program built from the firmware's own pcd_protocol.c. Each input
# line is either
#     e <node_id> <seq> <uptime_ms> <temp> <humidity> <flags>
# (encode: prints the packet as hex) or
#     d <hex>
# (decode: prints "ok <fields...>" or "error <code>").
C_PROGRAM = r"""
#include <stdio.h>
#include <string.h>
#include "pcd_protocol.h"

int main(void)
{
    char line[256];
    while (fgets(line, sizeof line, stdin) != NULL) {
        unsigned long node, seq, up, hum, flags;
        long temp;
        char hex[128];
        if (sscanf(line, "e %lu %lu %lu %ld %lu %lu", &node, &seq, &up, &temp, &hum, &flags) == 6) {
            pcd_reading_t r;
            uint8_t buf[PCD_PACKET_SIZE];
            size_t i;
            r.node_id = (uint32_t)node;
            r.seq = (uint32_t)seq;
            r.uptime_ms = (uint32_t)up;
            r.temp_centi_c = (int16_t)temp;
            r.humidity_centi_pct = (uint16_t)hum;
            r.flags = (uint8_t)flags;
            if (pcd_packet_encode(&r, buf, sizeof buf) != PCD_PACKET_SIZE) {
                printf("encode failed\n");
                continue;
            }
            for (i = 0; i < sizeof buf; i++) {
                printf("%02x", buf[i]);
            }
            printf("\n");
        } else if (sscanf(line, "d %127s", hex) == 1) {
            uint8_t buf[64];
            size_t n = strlen(hex) / 2, i;
            pcd_reading_t r;
            pcd_decode_result_t result;
            unsigned value;
            for (i = 0; i < n && i < sizeof buf; i++) {
                sscanf(hex + 2 * i, "%2x", &value);
                buf[i] = (uint8_t)value;
            }
            result = pcd_packet_decode(buf, n, &r);
            if (result != PCD_DECODE_OK) {
                printf("error %d\n", (int)result);
            } else {
                printf("ok %lu %lu %lu %d %u %u\n", (unsigned long)r.node_id,
                       (unsigned long)r.seq, (unsigned long)r.uptime_ms, (int)r.temp_centi_c,
                       (unsigned)r.humidity_centi_pct, (unsigned)r.flags);
            }
        }
    }
    return 0;
}
"""

CASES = [
    GOLDEN_READING,
    Reading(0, 0, 0, 0, 0, 0),
    Reading(0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, -32768, 65535, 0xFF),
    Reading(0x80000000, 0x7FFFFFFF, 1, 32767, 10000, 0x01),
    Reading(0x12345678, 4294967295, 4294967000, -4500, 0, 0x02),  # seq about to wrap
    Reading(0xDEADBEEF, 0, 1500, 13000, 10000, 0x03),
    Reading(0x00000001, 1, 2500, -1, 1, 0x03),
]


@pytest.fixture(scope="module")
def c_tool(tmp_path_factory):
    compiler = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if compiler is None:
        pytest.skip("no C compiler (cc, gcc or clang) on this machine")
    folder = tmp_path_factory.mktemp("c_encoder")
    source = folder / "encoder.c"
    source.write_text(C_PROGRAM)
    exe = folder / "encoder"
    subprocess.run(
        [
            compiler,
            "-std=c99",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-I{FIRMWARE_LIB}",
            str(source),
            str(FIRMWARE_LIB / "pcd_protocol.c"),
            "-o",
            str(exe),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return exe


def run_c(exe: Path, lines: list[str]) -> list[str]:
    result = subprocess.run(
        [str(exe)], input="\n".join(lines) + "\n", check=True, capture_output=True, text=True
    )
    return result.stdout.splitlines()


def test_python_decodes_c_packets_identically(c_tool):
    lines = [
        f"e {r.node_id} {r.seq} {r.uptime_ms} {r.temp_centi_c} {r.humidity_centi_pct} {r.flags}"
        for r in CASES
    ]
    hex_packets = run_c(c_tool, lines)
    assert len(hex_packets) == len(CASES)
    for expected, hex_packet in zip(CASES, hex_packets, strict=True):
        data = bytes.fromhex(hex_packet)
        assert decode(data) == expected  # Python reads what C wrote
        assert encode(expected) == data  # and would have written the same bytes


def test_c_decodes_python_packets_identically(c_tool):
    outputs = run_c(c_tool, [f"d {encode(r).hex()}" for r in CASES])
    for reading, line in zip(CASES, outputs, strict=True):
        r = reading
        assert line == (
            f"ok {r.node_id} {r.seq} {r.uptime_ms} {r.temp_centi_c} {r.humidity_centi_pct} {r.flags}"
        )


def test_c_and_python_reject_the_same_damage(c_tool):
    # Codes from pcd_decode_result_t: 2 length, 3 magic, 4 version, 5 crc.
    c_codes = {"length": "error 2", "magic": "error 3", "version": "error 4", "crc": "error 5"}
    damaged = [
        GOLDEN[:-1],
        b"Q" + GOLDEN[1:],
        GOLDEN[:2] + b"\x02" + GOLDEN[3:],
        GOLDEN[:16] + b"\x2a" + GOLDEN[17:],
    ]
    outputs = run_c(c_tool, [f"d {d.hex()}" for d in damaged])
    for data, line in zip(damaged, outputs, strict=True):
        with pytest.raises(PacketError) as caught:
            decode(data)
        assert line == c_codes[caught.value.reason]
