"""The case-sensor UDP packet, version 1.

This mirrors firmware/lib/pcd_protocol/src/pcd_protocol.h, which is the one
real description of the format. If you change one, change the other: the
tests compile the C encoder and check that both sides agree byte for byte.

One packet is 22 bytes, all multi-byte fields little-endian:

    offset  size  field       meaning
     0      2     magic       b"PD"
     2      1     version     1
     3      1     flags       bit 0: temperature is real, bit 1: humidity is real
     4      4     node_id     random number picked at each boot (uint32)
     8      4     seq         sample counter, 0 after boot, wraps after 2**32 - 1
    12      4     uptime_ms   milliseconds since boot when sampled (uint32)
    16      2     temp        0.01 degC, signed (int16)
    18      2     humidity    0.01 %, unsigned (uint16)
    20      2     crc16       CRC-16/CCITT-FALSE of bytes 0..19
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"PD"
VERSION = 1
PACKET_SIZE = 22
CRC_OFFSET = 20  # the CRC covers every byte before this offset
DEFAULT_PORT = 9750
UINT32_MAX = 0xFFFFFFFF  # seq and uptime_ms wrap to 0 after this

FLAG_TEMP_VALID = 0x01
FLAG_HUMIDITY_VALID = 0x02

# "<" = little-endian, no padding. 2s = magic, B = uint8, I = uint32,
# h = int16, H = uint16. The CRC is packed separately because it is computed
# over the bytes this produces.
_BODY = struct.Struct("<2sBBIIIhH")
_CRC = struct.Struct("<H")
assert _BODY.size == CRC_OFFSET
assert _BODY.size + _CRC.size == PACKET_SIZE


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: polynomial 0x1021, start 0xFFFF, no reflection,
    no final XOR. Bit by bit, exactly like the C version.

    The standard check value is crc16(b"123456789") == 0x29B1.
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


@dataclass(frozen=True)
class Reading:
    """One decoded packet, with the raw integer fields kept as sent."""

    node_id: int
    seq: int
    uptime_ms: int
    temp_centi_c: int
    humidity_centi_pct: int
    flags: int = FLAG_TEMP_VALID | FLAG_HUMIDITY_VALID

    @property
    def temp_c(self) -> float | None:
        """Temperature in degC, or None when the sensor read failed."""
        if self.flags & FLAG_TEMP_VALID:
            return self.temp_centi_c / 100
        return None

    @property
    def humidity_pct(self) -> float | None:
        """Relative humidity in %, or None when the sensor read failed."""
        if self.flags & FLAG_HUMIDITY_VALID:
            return self.humidity_centi_pct / 100
        return None


class PacketError(ValueError):
    """A datagram that is not a good version-1 packet.

    `reason` is one short word ("length", "magic", "version", "crc") so the
    receiver can count each kind of rejection separately.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def encode(reading: Reading) -> bytes:
    """Builds the 22 bytes for a reading. Raises struct.error if a field is
    out of range for its type (for example a negative seq)."""
    body = _BODY.pack(
        MAGIC,
        VERSION,
        reading.flags,
        reading.node_id,
        reading.seq,
        reading.uptime_ms,
        reading.temp_centi_c,
        reading.humidity_centi_pct,
    )
    return body + _CRC.pack(crc16(body))


def decode(data: bytes) -> Reading:
    """Checks length, magic, version and CRC, in that order (the same order
    as the C decoder), then returns the reading. Raises PacketError."""
    if len(data) != PACKET_SIZE:
        raise PacketError("length", f"expected {PACKET_SIZE} bytes, got {len(data)}")
    if data[0:2] != MAGIC:
        raise PacketError("magic", f"does not start with {MAGIC!r}")
    if data[2] != VERSION:
        raise PacketError("version", f"packet version {data[2]}, this receiver reads {VERSION}")
    (sent_crc,) = _CRC.unpack_from(data, CRC_OFFSET)
    if sent_crc != crc16(data[:CRC_OFFSET]):
        raise PacketError("crc", "checksum does not match (corrupted or not ours)")
    _magic, _version, flags, node_id, seq, uptime_ms, temp, humidity = _BODY.unpack_from(data)
    return Reading(
        node_id=node_id,
        seq=seq,
        uptime_ms=uptime_ms,
        temp_centi_c=temp,
        humidity_centi_pct=humidity,
        flags=flags,
    )
