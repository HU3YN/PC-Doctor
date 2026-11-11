"""Command line: analyse a run folder, or just summarise a PresentMon CSV.

pcdoctor-analyze path/to/PCDoctor-run-...      full diagnosis
pcdoctor-analyze frames path/to/presentmon.csv FPS, 1% low, spikes
pcdoctor-analyze rules                         list every check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analyze import analyze_run_dir
from .model import Thresholds
from .presentmon import PresentMonError, compute_frame_stats, parse_presentmon_csv
from .rules import all_rules

MARK = {"critical": "[CRITICAL]", "warning": "[WARNING] ", "info": "[info]    "}


def _frames(path: Path, process: str | None) -> int:
    try:
        data = parse_presentmon_csv(path, process)
    except (PresentMonError, OSError) as error:
        print(f"Could not read {path}: {error}", file=sys.stderr)
        return 2
    stats = compute_frame_stats(data, Thresholds())
    print(f"Application     {stats.application or '(unknown)'}")
    print(f"Frames          {stats.frames:,} over {stats.duration_s:.1f} s")
    print(f"Average FPS     {stats.avg_fps:.1f}")
    print(f"1% low FPS      {stats.fps_1pct_low:.1f}   (average of the slowest 1% of frames)")
    print(f"0.1% low FPS    {stats.fps_01pct_low:.1f}")
    print(
        f"Frame time      median {stats.frame_time_median_ms:.2f} ms, "
        f"99th percentile {stats.frame_time_p99_ms:.2f} ms, worst {stats.frame_time_max_ms:.1f} ms"
    )
    print(
        f"Spikes          {stats.spike_count} ({stats.spikes_per_min:.1f} per minute), "
        f"{stats.hitch_count} of them 100 ms or longer"
    )
    for note in data.notes:
        print(f"Note: {note}")
    if not stats.enough_frames:
        print("Note: too few frames for the percentiles to mean much.")
    return 0


def _rules() -> int:
    rules = all_rules()
    for entry in rules:
        print(f"{entry.code:32} {entry.detects}")
    print(f"\n{len(rules)} fault types")
    return 0


def _run(path: Path, as_json: bool) -> int:
    try:
        result = analyze_run_dir(path)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 2
    if as_json:
        json.dump(result.to_dict(), sys.stdout, indent=2)
        print()
        return 0
    device = result.device
    print(f"{result.verdict.upper()}: {result.headline}")
    print(
        " | ".join(
            str(v)
            for v in (
                device.get("cpu"),
                device.get("gpu"),
                f"{device.get('ram_gb')} GB RAM" if device.get("ram_gb") else None,
            )
            if v
        )
    )
    print()
    for finding in result.findings:
        print(f"{MARK[finding.severity.value]} {finding.title}")
        print(f"    {finding.summary}")
        for number, check in enumerate(finding.next_checks, 1):
            print(f"      {number}. {check}")
        print()
    passed = [c.title for c in result.checks if c.status == "passed"]
    skipped = [c.title for c in result.checks if c.status == "no_data"]
    print(f"Passed ({len(passed)}): " + ", ".join(passed))
    print(f"Not checked - no data ({len(skipped)}): " + ", ".join(skipped))
    for note in result.notes:
        print(f"Note: {note}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "frames":
        parser = argparse.ArgumentParser(prog="pcdoctor-analyze frames")
        parser.add_argument("csv", type=Path, help="a PresentMon CSV file")
        parser.add_argument("--process", help="analyse this process, e.g. game.exe")
        args = parser.parse_args(argv[1:])
        return _frames(args.csv, args.process)
    if argv and argv[0] == "rules":
        return _rules()
    parser = argparse.ArgumentParser(
        prog="pcdoctor-analyze", description="Diagnose a PC Doctor run folder."
    )
    parser.add_argument("run_dir", type=Path, help="folder written by the collector")
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = parser.parse_args(argv)
    return _run(args.run_dir, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
