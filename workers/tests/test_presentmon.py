from __future__ import annotations

import io

import pytest

from pcdoctor_analysis.model import Thresholds
from pcdoctor_analysis.presentmon import (
    PresentMonError,
    compute_frame_stats,
    find_spikes,
    parse_presentmon_csv,
    percentile,
)

from .conftest import make_frames

# The three header styles PresentMon has used (see presentmon.py).
DEFAULT_2X = "Application,ProcessID,SwapChainAddress,TimeInSeconds,MsBetweenPresents,MsGPUBusy,MsCPUBusy,MsUntilDisplayed"
V2_METRICS = (
    "Application,ProcessID,SwapChainAddress,CPUStartTime,FrameTime,GPUBusy,CPUBusy,DisplayedTime"
)
V1_METRICS = (
    "Application,ProcessID,SwapChainAddress,Dropped,TimeInSeconds,msBetweenPresents,msGPUActive"
)


def csv_text(header: str, rows: list[str]) -> io.StringIO:
    return io.StringIO(header + "\n" + "\n".join(rows) + "\n")


def rows_for(app: str, count: int, ft: float = 10.0, extra: str = "8.0,4.0,12.0") -> list[str]:
    return [f"{app},100,0xA,{i * ft / 1000:.4f},{ft},{extra}" for i in range(count)]


@pytest.mark.parametrize("header", [DEFAULT_2X, V2_METRICS])
def test_reads_every_2x_header_style(header):
    data = parse_presentmon_csv(csv_text(header, rows_for("game.exe", 50)))
    assert data.application == "game.exe"
    assert data.frame_times_ms == [10.0] * 50
    assert data.gpu_busy_ms == [8.0] * 50
    assert data.cpu_busy_ms == [4.0] * 50


def test_reads_v1_header_and_counts_dropped_frames():
    rows = [f"game.exe,1,0xA,{1 if i % 10 == 0 else 0},{i * 0.01:.2f},10.0,7.5" for i in range(40)]
    data = parse_presentmon_csv(csv_text(V1_METRICS, rows))
    assert len(data.frame_times_ms) == 40
    assert data.dropped_frames == 4
    assert data.gpu_busy_ms == [7.5] * 40


def test_header_lookup_ignores_case_and_byte_order_mark(tmp_path):
    path = tmp_path / "pm.csv"
    path.write_bytes(
        b"\xef\xbb\xbfAPPLICATION,processid,SwapChainAddress,timeinseconds,MSBETWEENPRESENTS\n"
        b"game.exe,1,0xA,0.0,5.0\ngame.exe,1,0xA,0.005,5.0\n"
    )
    data = parse_presentmon_csv(path)
    assert data.frame_times_ms == [5.0, 5.0]


def test_picks_the_busiest_process_and_ignores_the_windows_shell():
    rows = rows_for("dwm.exe", 500) + rows_for("game.exe", 200) + rows_for("launcher.exe", 30)
    data = parse_presentmon_csv(csv_text(DEFAULT_2X, rows))
    assert data.application == "game.exe"
    assert data.other_applications == 2


def test_target_process_wins_and_matches_without_exe_or_case():
    rows = rows_for("game.exe", 200) + rows_for("Benchmark.exe", 50)
    data = parse_presentmon_csv(csv_text(DEFAULT_2X, rows), target_process="benchmark")
    assert data.application == "Benchmark.exe"


def test_missing_target_process_falls_back_with_a_note():
    data = parse_presentmon_csv(csv_text(DEFAULT_2X, rows_for("game.exe", 20)), "other.exe")
    assert data.application == "game.exe"
    assert any("other.exe" in note for note in data.notes)


def test_only_shell_processes_is_noted():
    data = parse_presentmon_csv(csv_text(DEFAULT_2X, rows_for("dwm.exe", 20)))
    assert data.application == "dwm.exe"
    assert any("shell" in note for note in data.notes)


def test_uses_the_busiest_swap_chain_of_the_process():
    main = [f"game.exe,1,0xMAIN,{i * 0.01:.2f},10.0,8,4,12" for i in range(100)]
    overlay = [f"game.exe,1,0xOVERLAY,{i * 0.1:.2f},100.0,8,4,12" for i in range(10)]
    data = parse_presentmon_csv(csv_text(DEFAULT_2X, main + overlay))
    assert data.frame_times_ms == [10.0] * 100


def test_na_and_zero_frame_times_are_skipped_and_na_display_counts_as_dropped():
    rows = [
        "game.exe,1,0xA,0.00,NA,8,4,12",
        "game.exe,1,0xA,0.01,0,8,4,12",
        "game.exe,1,0xA,0.02,10.0,8,4,NA",
        "game.exe,1,0xA,0.03,10.0,8,4,12",
    ]
    data = parse_presentmon_csv(csv_text(DEFAULT_2X, rows))
    assert data.frame_times_ms == [10.0, 10.0]
    assert data.dropped_frames == 1


@pytest.mark.parametrize(
    "text, message",
    [
        ("", "empty"),
        ("Application,ProcessID,SomethingElse\ngame.exe,1,2\n", "frame-time column"),
        (DEFAULT_2X + "\n", "no frames"),
    ],
)
def test_unusable_files_raise_a_clear_error(text, message):
    with pytest.raises(PresentMonError, match=message):
        parse_presentmon_csv(io.StringIO(text))


def test_elapsed_time_uses_the_timestamp_column_in_seconds_or_milliseconds():
    seconds = parse_presentmon_csv(csv_text(DEFAULT_2X, rows_for("g.exe", 5)))
    assert seconds.elapsed_s == pytest.approx([0, 0.01, 0.02, 0.03, 0.04])
    header = DEFAULT_2X.replace("TimeInSeconds", "TimeInMs")
    rows = [f"g.exe,1,0xA,{i * 10.0},10.0,8,4,12" for i in range(5)]
    millis = parse_presentmon_csv(csv_text(header, rows))
    assert millis.elapsed_s == pytest.approx([0, 0.01, 0.02, 0.03, 0.04])


def test_elapsed_time_falls_back_to_summing_when_the_timestamps_make_no_sense():
    rows = [f"g.exe,1,0xA,{9999 - i},10.0,8,4,12" for i in range(4)]  # going backwards
    data = parse_presentmon_csv(csv_text(DEFAULT_2X, rows))
    assert data.elapsed_s == pytest.approx([0, 0.01, 0.02, 0.03])


def test_percentile_interpolates():
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([10], 99) == 10
    assert percentile([0, 10], 25) == 2.5


def test_frame_stats_on_a_run_worked_out_by_hand():
    # 990 frames of 10 ms and 10 frames of 50 ms: 10.4 s in total.
    frames = [10.0] * 990 + [50.0] * 10
    stats = compute_frame_stats(make_frames(frames), Thresholds())
    assert stats.frames == 1000
    assert stats.duration_s == pytest.approx(10.4)
    assert stats.avg_fps == pytest.approx(1000 / 10.4)  # frames / seconds, not mean of FPS
    assert stats.median_fps == pytest.approx(100.0)
    assert stats.fps_1pct_low == pytest.approx(20.0)  # slowest 1% = the ten 50 ms frames
    assert stats.frame_time_max_ms == 50.0
    assert stats.low_ratio == pytest.approx(20.0 / (1000 / 10.4))
    assert stats.enough_frames


def test_spikes_are_judged_against_recent_frames_not_the_whole_run():
    t = Thresholds()
    smooth = [10.0] * 100
    assert find_spikes(smooth, t) == []
    one_long = [10.0] * 50 + [40.0] + [10.0] * 50
    assert find_spikes(one_long, t) == [50]
    # A slow scene (every frame 40 ms from here on) is one event, not fifty.
    slow_scene = [10.0] * 50 + [40.0] * 50
    assert find_spikes(slow_scene, t) == [50]
    # ...and a real spike inside the slow scene is still found.
    assert find_spikes(slow_scene + [130.0] + [40.0] * 20, t) == [50, 100]
    # A burst of long frames counts once; frames after it are judged normally.
    burst = [10.0] * 50 + [120.0] * 4 + [10.0] * 50 + [60.0] + [10.0] * 20
    assert find_spikes(burst, t) == [50, 104]


def test_a_small_wobble_at_high_fps_is_not_a_spike():
    # 4 ms -> 9 ms is more than double but only 5 ms extra: nobody feels that.
    assert find_spikes([4.0] * 50 + [9.0] + [4.0] * 50, Thresholds()) == []


def test_hitches_and_spike_rate():
    frames = ([10.0] * 200 + [150.0]) * 5
    stats = compute_frame_stats(make_frames(frames), Thresholds())
    assert stats.spike_count == 5
    assert stats.hitch_count == 5
    assert stats.spikes_per_min == pytest.approx(5 / (stats.duration_s / 60))


def test_gpu_busy_share():
    data = make_frames([10.0] * 400, gpu_busy_ms=[9.0] * 400, cpu_busy_ms=[3.0] * 400)
    stats = compute_frame_stats(data)
    assert stats.gpu_busy_share == pytest.approx(0.9)
    assert stats.cpu_busy_share == pytest.approx(0.3)


def test_short_captures_are_flagged_as_too_short():
    assert not compute_frame_stats(make_frames([10.0] * 50)).enough_frames


def test_a_long_capture_is_fast_enough():
    import time

    frames = [4.2 + (i % 7) * 0.1 for i in range(150_000)]  # ~10 minutes at 240 FPS
    start = time.perf_counter()
    compute_frame_stats(make_frames(frames))
    assert time.perf_counter() - start < 5
