"""Sequence tracking: loss, duplicates, reordering, wrap-around and reboots."""

from __future__ import annotations

from case_sensor import tracker
from case_sensor.packet import Reading
from case_sensor.tracker import SequenceTracker

NODE = 0xA1B2C3D4


def reading(seq: int, node: int = NODE, uptime_ms: int | None = None) -> Reading:
    if uptime_ms is None:
        uptime_ms = 1000 + 1000 * (seq % 1_000_000)
    return Reading(node, seq, uptime_ms, 2500, 4000)


def feed(t: SequenceTracker, seqs: list[int], node: int = NODE) -> list[str]:
    return [t.handle(reading(s, node), arrival_s=float(i)).kind for i, s in enumerate(seqs)]


def test_clean_run_has_no_loss():
    t = SequenceTracker()
    kinds = feed(t, [0, 1, 2, 3, 4])
    assert kinds == ["first", "next", "next", "next", "next"]
    boot = t.boots[0]
    assert (boot.expected, boot.unique, boot.lost) == (5, 5, 0)


def test_gap_counts_as_loss():
    t = SequenceTracker()
    feed(t, [0, 1, 5, 6])
    result = t.handle(reading(9), 10.0)
    assert result.kind == tracker.GAP
    assert result.missing == 2
    boot = t.boots[0]
    assert boot.expected == 10
    assert boot.lost == 5  # 2, 3, 4, 7, 8


def test_duplicate_is_ignored():
    t = SequenceTracker()
    kinds = feed(t, [0, 1, 1, 2, 0])
    assert kinds == ["first", "next", "duplicate", "next", "duplicate"]
    boot = t.boots[0]
    assert boot.duplicates == 2
    assert boot.unique == 3
    assert boot.lost == 0


def test_late_packet_fills_its_gap():
    t = SequenceTracker()
    kinds = feed(t, [0, 1, 3, 2, 4])
    assert kinds == ["first", "next", "gap", "late", "next"]
    boot = t.boots[0]
    assert boot.reordered == 1
    assert boot.lost == 0


def test_late_packet_before_the_first_one_extends_the_span():
    t = SequenceTracker()
    kinds = feed(t, [10, 11, 9])
    assert kinds == ["first", "next", "late"]
    boot = t.boots[0]
    assert boot.first_seq == 9
    assert (boot.expected, boot.lost) == (3, 0)


def test_wrap_around_is_not_loss_or_reboot():
    top = 2**32 - 1
    t = SequenceTracker()
    kinds = feed(t, [top - 2, top - 1, top, 0, 1, 2])
    assert kinds == ["first", "next", "next", "next", "next", "next"]
    assert len(t.boots) == 1
    boot = t.boots[0]
    assert (boot.expected, boot.lost) == (6, 0)


def test_gap_and_reordering_across_the_wrap():
    top = 2**32 - 1
    t = SequenceTracker()
    kinds = feed(t, [top - 1, 1, top, 0])
    assert kinds == ["first", "gap", "late", "late"]
    boot = t.boots[0]
    assert (boot.expected, boot.unique, boot.lost, boot.reordered) == (4, 4, 0, 2)


def test_duplicate_across_the_wrap():
    top = 2**32 - 1
    t = SequenceTracker()
    assert feed(t, [top, 0, top]) == ["first", "next", "duplicate"]


def test_new_node_id_is_a_new_boot():
    t = SequenceTracker()
    feed(t, [0, 1, 2, 3])
    result = t.handle(reading(0, node=0x11111111), 5.0)
    assert result.kind == tracker.FIRST
    assert len(t.boots) == 2
    # Nothing is counted lost across the restart.
    assert sum(b.lost for b in t.boots) == 0


def test_same_id_restart_detected_by_seq_and_uptime_going_back():
    t = SequenceTracker()
    feed(t, list(range(5000, 5010)))
    result = t.handle(reading(0, uptime_ms=1500), 20.0)
    assert result.kind == tracker.FIRST
    assert len(t.boots) == 2


def test_very_old_packet_without_restart_is_ignored():
    t = SequenceTracker()
    feed(t, list(range(5000, 5010)))
    # Far behind but the node's clock did NOT go back: not a restart.
    result = t.handle(reading(10, uptime_ms=10**9), 20.0)
    assert result.kind == tracker.TOO_OLD
    assert len(t.boots) == 1


def test_sample_interval_uses_the_node_clock():
    t = SequenceTracker()
    for i, seq in enumerate([0, 1, 3, 4]):  # 2 lost
        t.handle(reading(seq, uptime_ms=500 + 250 * seq), arrival_s=float(i) * 7)
    boot = t.boots[0]
    assert boot.intervals == 4
    assert boot.node_elapsed_ms == 1000


def test_long_run_keeps_memory_bounded():
    t = SequenceTracker()
    for seq in range(3 * tracker.WINDOW):
        t.handle(reading(seq), float(seq))
    boot = t.boots[0]
    assert len(boot.seen) <= 2 * tracker.WINDOW
    assert boot.lost == 0
