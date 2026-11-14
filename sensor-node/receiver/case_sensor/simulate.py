"""A pretend sensor node, for trying the receiver without any hardware.

It behaves like the firmware: one sample per interval, seq counts samples
TAKEN, and --loss drops that fraction of packets on purpose (the seq still
goes up), so the receiver's loss figure can be checked against a known value.
"""

from __future__ import annotations

import math
import random
import socket
import time
from collections.abc import Iterator

from .packet import FLAG_HUMIDITY_VALID, FLAG_TEMP_VALID, UINT32_MAX, Reading, encode


def readings(
    node_id: int, start_seq: int = 0, interval_ms: int = 1000, seed: int | None = None
) -> Iterator[Reading]:
    """Endless made-up readings: case air warming and cooling slowly around
    32 degC, humidity drifting the other way, with a little noise."""
    rng = random.Random(seed)
    seq = start_seq
    uptime_ms = 1500  # a real node takes about this long to boot and join Wi-Fi
    while True:
        minutes = uptime_ms / 60000
        temp_c = 32.0 + 4.0 * math.sin(minutes) + rng.gauss(0, 0.05)
        humidity = 38.0 - 3.0 * math.sin(minutes) + rng.gauss(0, 0.1)
        yield Reading(
            node_id=node_id,
            seq=seq,
            uptime_ms=uptime_ms,
            temp_centi_c=round(temp_c * 100),
            humidity_centi_pct=round(humidity * 100),
            flags=FLAG_TEMP_VALID | FLAG_HUMIDITY_VALID,
        )
        seq = (seq + 1) & UINT32_MAX  # wraps to 0 like the C uint32
        uptime_ms = (uptime_ms + interval_ms) & UINT32_MAX


def run(
    host: str,
    port: int,
    rate_hz: float = 1.0,
    count: int | None = None,
    loss: float = 0.0,
    start_seq: int = 0,
    seed: int | None = None,
    quiet: bool = False,
) -> tuple[int, int]:
    """Sends `count` samples (or forever, until Ctrl+C) and returns
    (samples taken, packets actually sent)."""
    if rate_hz <= 0:
        raise ValueError("rate must be above 0")
    if not 0.0 <= loss < 1.0:
        raise ValueError("loss must be a fraction from 0 up to (not including) 1")

    rng = random.Random(seed)
    node_id = rng.getrandbits(32)  # a new id each run, like a reboot
    interval_s = 1.0 / rate_hz
    samples = readings(node_id, start_seq, round(interval_s * 1000), seed)
    taken = 0
    sent = 0
    if not quiet:
        print(f"Simulated node {node_id:08x} sending to {host}:{port}")
        print(f"{rate_hz:g} samples a second, dropping {loss:.0%} on purpose")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    next_time = time.monotonic()
    try:
        while count is None or taken < count:
            reading = next(samples)
            taken += 1
            if rng.random() >= loss:
                sock.sendto(encode(reading), (host, port))
                sent += 1
            elif not quiet:
                print(f"  dropped seq={reading.seq} on purpose")
            if count is not None and taken >= count:
                break
            # Same scheduling as the firmware: from the previous deadline, so
            # the rate does not drift.
            next_time += interval_s
            delay = next_time - time.monotonic()
            if delay > 0:
                time.sleep(delay)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
    if not quiet:
        print(f"Took {taken} samples, sent {sent}, dropped {taken - sent}")
    return taken, sent
