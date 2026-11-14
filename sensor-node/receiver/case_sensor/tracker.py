"""Sequence-number bookkeeping: what was lost, duplicated or arrived late.

The node numbers every sample it TAKES (seq = 0, 1, 2, ...), whether or not
the packet gets sent, so a gap in the numbers the receiver sees is real lost
data. Four things make this less simple than "count the gaps":

* Wrap-around. seq is a uint32 and goes 4294967295 -> 0. All comparisons are
  done modulo 2**32: "b is ahead of a" means (b - a) % 2**32 is less than
  2**31. That is the usual serial-number trick (RFC 1982).
* Reordering. UDP can deliver 7 before 6. A packet behind the highest seq
  seen so far is a late arrival, not a reset, and it fills its gap back in.
* Duplicates. A network can deliver the same datagram twice. The receiver
  remembers the last WINDOW sequence numbers it saw so it can drop repeats.
* Reboots. The node picks a new random node_id at every boot, so a new id
  starts a new "boot" with its own count. In the 1-in-4-billion case that the
  id repeats, the seq jumping far back while uptime_ms also goes back is
  treated as a restart too.

Loss is worked out from the span rather than by adding up gaps, so a late
packet automatically stops counting as lost:

    expected = highest_seq - first_seq + 1      (modulo 2**32)
    lost     = expected - unique packets received
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .packet import Reading

SEQ_MOD = 2**32
HALF = 2**31

# How many sequence numbers back we remember. At 1 sample a second this is
# over an hour, far more than any real network delays a packet.
WINDOW = 4096

# What happened to one packet. The receiver writes a CSV row for every kind
# except DUPLICATE and TOO_OLD.
FIRST = "first"  # first packet of a new boot (new node id or restart)
NEXT = "next"  # exactly the next number - the normal case
GAP = "gap"  # ahead of the next number: the ones in between are missing
LATE = "late"  # behind the highest seen, not seen before: reordered
DUPLICATE = "duplicate"  # seen this number already
TOO_OLD = "too_old"  # so far behind that we cannot tell; ignored


def seq_distance(a: int, b: int) -> int:
    """How far b is ahead of a, counting through the wrap: 0 .. 2**32 - 1."""
    return (b - a) % SEQ_MOD


@dataclass
class Boot:
    """Everything known about one run of one node, from power-on to reset."""

    node_id: int
    first_seq: int
    highest_seq: int
    uptime_at_first_ms: int
    uptime_at_highest_ms: int
    first_arrival_s: float
    last_arrival_s: float
    unique: int = 1
    duplicates: int = 0
    reordered: int = 0
    too_old: int = 0
    seen: set[int] = field(default_factory=set)

    @property
    def expected(self) -> int:
        """How many samples the node took between the first and the highest
        sequence number we received (both included)."""
        return seq_distance(self.first_seq, self.highest_seq) + 1

    @property
    def lost(self) -> int:
        return max(self.expected - self.unique, 0)

    @property
    def intervals(self) -> int:
        """Sample intervals between the first and highest seq: expected - 1."""
        return seq_distance(self.first_seq, self.highest_seq)

    @property
    def node_elapsed_ms(self) -> int:
        """Time between those two samples by the NODE's own clock (uptime_ms),
        so Wi-Fi delays do not affect it. Modulo 2**32 because uptime_ms
        wraps too, after about 49.7 days."""
        return (self.uptime_at_highest_ms - self.uptime_at_first_ms) % SEQ_MOD


@dataclass(frozen=True)
class Result:
    """What the tracker decided about one packet."""

    kind: str
    boot: Boot
    missing: int = 0  # for GAP: how many sequence numbers were skipped


class SequenceTracker:
    """Feed it every valid packet with handle(); it keeps one Boot per run."""

    def __init__(self) -> None:
        self.boots: list[Boot] = []  # every boot, oldest first
        self._current: dict[int, Boot] = {}  # node_id -> its latest boot

    def handle(self, reading: Reading, arrival_s: float) -> Result:
        boot = self._current.get(reading.node_id)
        if boot is None:
            return Result(FIRST, self._start_boot(reading, arrival_s))

        boot.last_arrival_s = arrival_s
        seq = reading.seq
        ahead = seq_distance(boot.highest_seq, seq)

        if ahead == 0:
            boot.duplicates += 1
            return Result(DUPLICATE, boot)

        if ahead < HALF:
            # Newer than anything so far. ahead == 1 is the normal case.
            boot.unique += 1
            boot.highest_seq = seq
            boot.uptime_at_highest_ms = reading.uptime_ms
            self._remember(boot, seq)
            if ahead == 1:
                return Result(NEXT, boot)
            return Result(GAP, boot, missing=ahead - 1)

        # Behind the highest seen.
        behind = seq_distance(seq, boot.highest_seq)
        if behind < WINDOW:
            if seq in boot.seen:
                boot.duplicates += 1
                return Result(DUPLICATE, boot)
            boot.unique += 1
            boot.reordered += 1
            self._remember(boot, seq)
            if seq_distance(seq, boot.first_seq) < HALF:
                # Even older than the first packet we got: the span grows.
                boot.first_seq = seq
                boot.uptime_at_first_ms = reading.uptime_ms
            return Result(LATE, boot)

        if reading.uptime_ms < boot.uptime_at_highest_ms:
            # Far behind AND the node's clock went back: it restarted and,
            # against the odds, picked the same id.
            return Result(FIRST, self._start_boot(reading, arrival_s))

        boot.too_old += 1
        return Result(TOO_OLD, boot)

    def _start_boot(self, reading: Reading, arrival_s: float) -> Boot:
        boot = Boot(
            node_id=reading.node_id,
            first_seq=reading.seq,
            highest_seq=reading.seq,
            uptime_at_first_ms=reading.uptime_ms,
            uptime_at_highest_ms=reading.uptime_ms,
            first_arrival_s=arrival_s,
            last_arrival_s=arrival_s,
        )
        boot.seen.add(reading.seq)
        self.boots.append(boot)
        self._current[reading.node_id] = boot
        return boot

    @staticmethod
    def _remember(boot: Boot, seq: int) -> None:
        boot.seen.add(seq)
        # Forget numbers that fell out of the window, but only now and then,
        # so this is not a full pass over the set for every packet.
        if len(boot.seen) > 2 * WINDOW:
            boot.seen = {s for s in boot.seen if seq_distance(s, boot.highest_seq) < WINDOW}
