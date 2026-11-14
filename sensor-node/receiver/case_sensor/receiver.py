"""Listen for case-sensor packets, write them to CSV, and keep the score.

The work is split in two so it can be tested without a network:

* Receiver.handle_datagram() takes the bytes of one datagram and the time it
  arrived, and does everything: check, track, write the CSV row.
* listen() is the thin loop that reads datagrams off a UDP socket and hands
  them over.
"""

from __future__ import annotations

import csv
import socket
import threading
import time
from collections import Counter
from dataclasses import dataclass
from typing import TextIO

from . import tracker
from .packet import PacketError, Reading, decode

CSV_HEADER = ["elapsed_s", "case_temp_c", "case_humidity_pct"]


@dataclass(frozen=True)
class Summary:
    """The numbers printed at the end of a run."""

    duration_s: float
    packets: int  # valid packets, duplicates included
    unique: int  # distinct samples received
    duplicates: int
    reordered: int
    too_old: int
    expected: int  # samples the node took, judging by the sequence numbers
    lost: int
    rejected: dict[str, int]  # reason -> count
    boots: int  # distinct node runs (a restart picks a new node id)
    sample_interval_ms: float | None  # by the node's own clock
    arrival_span_s: float  # first to last packet of each boot, added up

    @property
    def loss_pct(self) -> float | None:
        if self.expected == 0:
            return None
        return 100.0 * self.lost / self.expected

    @property
    def sample_rate_hz(self) -> float | None:
        if not self.sample_interval_ms:
            return None
        return 1000.0 / self.sample_interval_ms

    @property
    def receive_rate_hz(self) -> float | None:
        """Packets that got through per second, by this computer's clock,
        between the first and last packet (so time spent waiting before the
        node started does not count). Roughly sample rate x (1 - loss)."""
        if self.arrival_span_s <= 0:
            return None
        return (self.unique - self.boots) / self.arrival_span_s

    def format(self) -> str:
        def maybe(value: float | None, fmt: str) -> str:
            return "n/a" if value is None else format(value, fmt)

        rejected = sum(self.rejected.values())
        reasons = ", ".join(f"{k} {v}" for k, v in sorted(self.rejected.items()))
        lines = [
            "Summary",
            f"  listened for       {self.duration_s:.1f} s",
            f"  packets            {self.packets} ({self.unique} unique samples)",
            f"  expected samples   {self.expected}",
            f"  lost               {self.lost}",
            f"  loss               {maybe(self.loss_pct, '.2f')} %",
            f"  duplicates         {self.duplicates}",
            f"  reordered          {self.reordered}",
            f"  rejected           {rejected}" + (f" ({reasons})" if reasons else ""),
            f"  node boots seen    {self.boots}",
            f"  sample rate        {maybe(self.sample_rate_hz, '.3f')} Hz (node clock)",
            f"  receive rate       {maybe(self.receive_rate_hz, '.3f')} Hz (this computer)",
        ]
        if self.too_old:
            lines.append(f"  too late to place  {self.too_old}")
        return "\n".join(lines)


class Receiver:
    """Checks, tracks and records datagrams. Not tied to a socket."""

    def __init__(self, csv_file: TextIO | None, start_s: float) -> None:
        self.start_s = start_s
        self.tracker = tracker.SequenceTracker()
        self.rejected: Counter[str] = Counter()
        self.packets = 0
        self._writer = None
        if csv_file is not None:
            self._writer = csv.writer(csv_file)
            self._writer.writerow(CSV_HEADER)

    def handle_datagram(self, data: bytes, arrival_s: float) -> str:
        """Processes one datagram and returns a one-line description of it."""
        try:
            reading = decode(data)
        except PacketError as error:
            self.rejected[error.reason] += 1
            return f"rejected ({error.reason}): {error}"

        self.packets += 1
        result = self.tracker.handle(reading, arrival_s)
        if result.kind in (tracker.DUPLICATE, tracker.TOO_OLD):
            return f"seq={reading.seq} {result.kind}, ignored"

        elapsed_s = arrival_s - self.start_s
        self._write_row(elapsed_s, reading)
        return describe(reading, result)

    def _write_row(self, elapsed_s: float, reading: Reading) -> None:
        if self._writer is None:
            return
        temp = reading.temp_c
        humidity = reading.humidity_pct
        # A failed sensor read leaves the field empty rather than writing 0,
        # which would look like a real (and alarming) reading.
        self._writer.writerow(
            [
                f"{elapsed_s:.3f}",
                "" if temp is None else f"{temp:.2f}",
                "" if humidity is None else f"{humidity:.2f}",
            ]
        )

    def summary(self, now_s: float) -> Summary:
        boots = self.tracker.boots
        # Sample interval by the node's clock: all the time covered, divided
        # by all the intervals covered, over every boot together.
        intervals = sum(b.intervals for b in boots)
        node_ms = sum(b.node_elapsed_ms for b in boots)
        interval_ms = node_ms / intervals if intervals else None
        return Summary(
            duration_s=now_s - self.start_s,
            packets=self.packets,
            unique=sum(b.unique for b in boots),
            duplicates=sum(b.duplicates for b in boots),
            reordered=sum(b.reordered for b in boots),
            too_old=sum(b.too_old for b in boots),
            expected=sum(b.expected for b in boots),
            lost=sum(b.lost for b in boots),
            rejected=dict(self.rejected),
            boots=len(boots),
            sample_interval_ms=interval_ms,
            arrival_span_s=sum(b.last_arrival_s - b.first_arrival_s for b in boots),
        )


def describe(reading: Reading, result: tracker.Result) -> str:
    """One line for the console, e.g. 'node 1a2b3c4d seq=12 31.25 C 40.10 %'."""
    temp = "no temp" if reading.temp_c is None else f"{reading.temp_c:.2f} C"
    humidity = "no humidity" if reading.humidity_pct is None else f"{reading.humidity_pct:.2f} %"
    line = f"node {reading.node_id:08x} seq={reading.seq} {temp} {humidity}"
    if result.kind == tracker.FIRST:
        line += "  <- new boot"
        if reading.seq != 0:
            line += f" (joined at seq {reading.seq}; earlier samples are not counted)"
    elif result.kind == tracker.GAP:
        line += f"  <- {result.missing} missing before this"
    elif result.kind == tracker.LATE:
        line += "  <- arrived late (reordered)"
    return line


def listen(
    host: str,
    port: int,
    csv_file: TextIO | None,
    duration_s: float | None = None,
    quiet: bool = False,
    ready: threading.Event | None = None,
) -> Summary:
    """Receives until duration_s has passed or Ctrl+C, then returns the summary.

    `ready`, if given, is set once the socket is bound (the tests use it to
    know when to start sending).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((host, port))
        # Wake up twice a second even with no traffic, so a duration limit
        # is noticed and Ctrl+C works promptly on every OS.
        sock.settimeout(0.5)
        start = time.monotonic()
        receiver = Receiver(csv_file, start)
        if ready is not None:
            ready.set()
        if not quiet:
            print(f"Listening on UDP {host}:{port} - Ctrl+C to stop")
        try:
            while duration_s is None or time.monotonic() - start < duration_s:
                try:
                    data, (sender, _port) = sock.recvfrom(2048)
                except TimeoutError:
                    continue
                line = receiver.handle_datagram(data, time.monotonic())
                if csv_file is not None:
                    csv_file.flush()  # so a crash or Ctrl+C loses nothing
                if not quiet:
                    print(f"{sender}: {line}")
        except KeyboardInterrupt:
            pass
        return receiver.summary(time.monotonic())
    finally:
        sock.close()
