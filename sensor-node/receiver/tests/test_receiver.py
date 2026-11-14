"""The receiver: CSV output, the summary, and a real UDP round trip with the
simulator."""

from __future__ import annotations

import csv
import io
import socket
import threading

import pytest

from case_sensor import receiver, simulate
from case_sensor.__main__ import main
from case_sensor.packet import FLAG_TEMP_VALID, Reading, encode


def packet(
    seq: int, temp: int = 3125, humidity: int = 4010, flags: int = 3, node: int = 7
) -> bytes:
    return encode(Reading(node, seq, 1000 + 1000 * seq, temp, humidity, flags))


def test_csv_rows_and_summary():
    out = io.StringIO()
    r = receiver.Receiver(out, start_s=100.0)
    r.handle_datagram(packet(0), 100.5)
    r.handle_datagram(packet(1), 101.5)
    r.handle_datagram(packet(1), 101.6)  # duplicate: no row
    r.handle_datagram(b"junk", 101.7)  # rejected: no row
    r.handle_datagram(packet(3, temp=-50, flags=FLAG_TEMP_VALID), 103.5)  # 2 is lost

    rows = list(csv.reader(io.StringIO(out.getvalue())))
    assert rows == [
        ["elapsed_s", "case_temp_c", "case_humidity_pct"],
        ["0.500", "31.25", "40.10"],
        ["1.500", "31.25", "40.10"],
        ["3.500", "-0.50", ""],  # humidity flag clear: empty, not 0
    ]

    s = r.summary(now_s=104.0)
    assert s.packets == 4
    assert s.unique == 3
    assert s.duplicates == 1
    assert s.expected == 4
    assert s.lost == 1
    assert s.loss_pct == 25.0
    assert s.rejected == {"length": 1}
    assert s.boots == 1
    assert s.sample_interval_ms == 1000.0
    assert s.sample_rate_hz == 1.0
    assert s.receive_rate_hz == 2 / 3.0  # 3 unique packets, 3 s from first to last
    text = s.format()
    assert "loss               25.00 %" in text
    assert "sample rate        1.000 Hz" in text


def test_summary_with_nothing_received():
    s = receiver.Receiver(None, start_s=0.0).summary(now_s=5.0)
    assert s.loss_pct is None
    assert s.sample_rate_hz is None
    assert "loss               n/a %" in s.format()


def test_describe_marks_gaps():
    r = receiver.Receiver(None, start_s=0.0)
    assert "new boot" in r.handle_datagram(packet(0), 0.0)
    assert "2 missing" in r.handle_datagram(packet(3), 1.0)
    assert "late" in r.handle_datagram(packet(1), 1.1)


def test_simulated_readings_wrap_like_the_firmware():
    samples = simulate.readings(node_id=1, start_seq=2**32 - 2, interval_ms=1000, seed=1)
    seqs = [next(samples).seq for _ in range(4)]
    assert seqs == [2**32 - 2, 2**32 - 1, 0, 1]


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_udp_round_trip_with_simulated_loss(tmp_path):
    """Simulator -> UDP on localhost -> receiver. The simulator reports how
    many it dropped on purpose; the receiver must count exactly that many lost
    (localhost does not lose packets of its own at this rate)."""
    port = free_udp_port()
    csv_path = tmp_path / "case.csv"
    ready = threading.Event()
    result = {}

    def listen():
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            result["summary"] = receiver.listen(
                "127.0.0.1", port, f, duration_s=3.0, quiet=True, ready=ready
            )

    thread = threading.Thread(target=listen)
    thread.start()
    assert ready.wait(5)
    # Start just below the wrap, so the round trip crosses it too.
    taken, sent = simulate.run(
        "127.0.0.1",
        port,
        rate_hz=200,
        count=300,
        loss=0.1,
        start_seq=2**32 - 100,
        seed=42,
        quiet=True,
    )
    thread.join(10)
    summary = result["summary"]

    # The last samples may have been dropped on purpose; the receiver cannot
    # know about samples after the last one it got, so compare up to there.
    assert summary.unique == sent
    assert summary.boots == 1
    assert summary.lost <= taken - sent
    assert taken - sent - summary.lost < 10
    assert summary.sample_rate_hz == pytest.approx(200, rel=0.01)
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["elapsed_s", "case_temp_c", "case_humidity_pct"]
    assert len(rows) == 1 + sent


def test_cli_help(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0
    assert "--simulate" in capsys.readouterr().out


def test_cli_rejects_bad_loss(capsys):
    with pytest.raises(SystemExit):
        main(["--simulate", "--loss", "1.5"])
    assert "loss" in capsys.readouterr().err
