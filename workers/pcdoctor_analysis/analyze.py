"""Turn a loaded run into the result the API stores and the dashboard shows."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .loader import RunData, load_run_dir
from .model import Finding, Severity, Thresholds
from .presentmon import compute_frame_stats
from .rules import Check, run_rules
from .sensors import summarize
from .series import frame_series, sensor_series


@dataclass
class AnalysisResult:
    rules_version: str
    verdict: str  # "critical" | "warning" | "ok"
    headline: str
    findings: list[Finding]
    checks: list[Check]
    device: dict[str, Any]
    frame_stats: dict[str, Any] | None
    sensor_stats: dict[str, dict[str, Any]]
    series: dict[str, Any]
    notes: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        counts = {"critical": 0, "warning": 0, "info": 0}
        for finding in self.findings:
            counts[finding.severity.value] += 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "rules_version": self.rules_version,
            "verdict": self.verdict,
            "headline": self.headline,
            "counts": self.counts,
            "findings": [f.to_dict() for f in self.findings],
            "checks": [c.to_dict() for c in self.checks],
            "device": self.device,
            "frame_stats": self.frame_stats,
            "sensor_stats": self.sensor_stats,
            "series": self.series,
            "notes": self.notes,
        }


def describe_device(specs: dict[str, Any]) -> dict[str, Any]:
    """The few lines that identify a build: CPU, GPU, RAM, board, Windows."""

    def first_name(items: Any) -> str | None:
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and str(item.get("name") or "").strip():
                    return str(item["name"]).strip()
        return None

    gpus = [g for g in specs.get("gpu", []) if isinstance(g, dict)] if specs else []
    # Prefer a real graphics card over the fallback driver, then the one with most memory.
    gpus.sort(
        key=lambda g: (
            "basic display" in str(g.get("name", "")).lower(),
            -(g.get("vram_bytes") or 0) if isinstance(g.get("vram_bytes"), (int, float)) else 0,
        )
    )
    memory = specs.get("memory") if isinstance(specs.get("memory"), dict) else {}
    total = memory.get("total_bytes")
    modules = memory.get("modules") or []
    board = specs.get("motherboard") if isinstance(specs.get("motherboard"), dict) else {}
    system = specs.get("system") if isinstance(specs.get("system"), dict) else {}
    os_info = specs.get("os") if isinstance(specs.get("os"), dict) else {}
    board_name = " ".join(
        str(board.get(k) or "").strip() for k in ("manufacturer", "product")
    ).strip()
    return {
        "cpu": first_name(specs.get("cpu")),
        "gpu": first_name(gpus),
        "ram_gb": round(total / 1024**3) if isinstance(total, (int, float)) and total else None,
        "ram_modules": len(modules) if modules else None,
        "motherboard": board_name or None,
        "system": " ".join(
            str(system.get(k) or "").strip() for k in ("manufacturer", "model")
        ).strip()
        or None,
        "type": system.get("type"),
        "os": os_info.get("caption"),
    }


def analyze_run(run: RunData, thresholds: Thresholds | None = None) -> AnalysisResult:
    from . import RULES_VERSION  # late import: __init__ imports this module

    thresholds = thresholds or Thresholds()
    findings, checks, errors = run_rules(run, thresholds)
    notes = list(run.notes) + errors

    frame_stats = None
    series: dict[str, Any] = {}
    if run.frames is not None:
        stats = compute_frame_stats(run.frames, thresholds)
        frame_stats = stats.to_dict()
        series["frames"] = frame_series(run.frames)
        if not stats.enough_frames:
            notes.append(
                f"Only {stats.frames} frames were captured, too few to judge stutter reliably."
            )
    from .rules.performance import idle_capture

    idle = idle_capture(run, thresholds)
    if idle is not None:
        notes.append(
            f"The PC was mostly idle during the capture (median GPU load {idle:.0f}%, no frame "
            "times), so this capture cannot show how it performs or how hot it runs under load. "
            "Start the game first and play during the whole capture - the collector's "
            "start delay gives time to switch to it."
        )
    sensor_stats: dict[str, dict[str, Any]] = {}
    if run.sensors is not None:
        sensor_stats = summarize(run.sensors)
        series["sensors"] = sensor_series(run.sensors)

    worst = max((f.severity.rank for f in findings), default=0)
    if worst >= Severity.CRITICAL.rank:
        verdict = "critical"
    elif worst >= Severity.WARNING.rank:
        verdict = "warning"
    else:
        verdict = "ok"
    checked = sum(1 for c in checks if c.status in ("passed", "found"))
    if verdict == "ok":
        headline = f"No faults found in {checked} checks"
    else:
        problems = [f for f in findings if f.severity.rank >= Severity.WARNING.rank]
        headline = problems[0].title
        if len(problems) > 1:
            headline += f" (+{len(problems) - 1} more)"

    return AnalysisResult(
        rules_version=RULES_VERSION,
        verdict=verdict,
        headline=headline,
        findings=findings,
        checks=checks,
        device=describe_device(run.specs),
        frame_stats=frame_stats,
        sensor_stats=sensor_stats,
        series=series,
        notes=notes,
    )


def analyze_run_dir(path: str | Path, thresholds: Thresholds | None = None) -> AnalysisResult:
    return analyze_run(load_run_dir(path), thresholds)
