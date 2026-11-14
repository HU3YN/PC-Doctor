"""Build comparison: where does this run sit among runs of the same build?

"Same build" means the same graphics card and the same game - frame rates
from different games say nothing about each other. Within that group the
question is asked twice: against every run with that card, and against the
runs that also have the same CPU, when there are enough of those.

The numbers are ranked with DuckDB, an in-process analytics database: the
peers' figures are loaded into an in-memory table and one SQL query works out
each figure's rank, median and quartiles. Nothing is shown below MIN_PEERS
runs: a rank among three runs means nothing, and saying so is better than a
confident-looking number.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Run

MIN_PEERS = 5
MAX_PEERS = 5000  # the newest; plenty for a rank

# (key, label, unit, higher is better)
METRICS: list[tuple[str, str, str, bool]] = [
    ("avg_fps", "Average FPS", "fps", True),
    ("fps_1pct_low", "1% low FPS", "fps", True),
    ("cpu_temp_peak", "CPU peak temperature", "°C", False),
    ("gpu_temp_peak", "GPU peak temperature", "°C", False),
]


def figures(run: Run) -> dict[str, Any]:
    """The figures compared, plus the game, from a stored run."""
    result = run.result or {}
    frames = result.get("frame_stats") or {}
    sensors = result.get("sensor_stats") or {}

    def peak(column: str) -> float | None:
        value = (sensors.get(column) or {}).get("max")
        return float(value) if isinstance(value, (int, float)) else None

    application = frames.get("application")
    return {
        "application": str(application).strip().lower() if application else None,
        "avg_fps": run.avg_fps,
        "fps_1pct_low": run.fps_1pct_low,
        "cpu_temp_peak": peak("cpu_temp_c"),
        "gpu_temp_peak": peak("gpu_temp_c"),
    }


def _rank(rows: list[dict[str, Any]], own: dict[str, Any]) -> dict[str, Any]:
    """Rank one run's figures among its peers' with a single DuckDB query per figure."""
    import duckdb

    connection = duckdb.connect()  # in memory; gone when this returns
    try:
        connection.execute(
            "CREATE TABLE peers (avg_fps DOUBLE, fps_1pct_low DOUBLE, "
            "cpu_temp_peak DOUBLE, gpu_temp_peak DOUBLE)"
        )
        connection.executemany(
            "INSERT INTO peers VALUES (?, ?, ?, ?)",
            [[row[key] for key, *_ in METRICS] for row in rows],
        )
        ranked = []
        for key, label, unit, higher_is_better in METRICS:
            value = own[key]
            if value is None:
                continue
            # The column name comes from METRICS above, never from a request.
            count, below, equal, q1, median, q3 = connection.execute(
                f"""
                SELECT count({key}),
                       count(*) FILTER (WHERE {key} < ?),
                       count(*) FILTER (WHERE {key} = ?),
                       quantile_cont({key}, 0.25),
                       quantile_cont({key}, 0.5),
                       quantile_cont({key}, 0.75)
                FROM peers WHERE {key} IS NOT NULL
                """,
                [value, value],
            ).fetchone()
            if count < MIN_PEERS:
                continue
            # The share of peers this run beats, counting ties as half.
            share_below = (below + equal / 2) / count
            better_than = share_below if higher_is_better else 1 - share_below
            ranked.append(
                {
                    "key": key,
                    "label": label,
                    "unit": unit,
                    "value": round(value, 1),
                    "peers": count,
                    "median": round(median, 1),
                    "q1": round(q1, 1),
                    "q3": round(q3, 1),
                    "better_than_pct": round(100 * better_than),
                    "higher_is_better": higher_is_better,
                }
            )
        return {"metrics": ranked}
    finally:
        connection.close()


def compare(db: Session, run: Run) -> dict[str, Any]:
    own = figures(run)
    answer: dict[str, Any] = {
        "gpu": run.gpu,
        "cpu": run.cpu,
        "application": (run.result or {}).get("frame_stats", {}).get("application"),
        "minimum": MIN_PEERS,
        "groups": [],
    }
    if not run.gpu or not own["application"]:
        answer["reason"] = "This run has no graphics card or no game capture to compare on."
        return answer
    candidates = db.scalars(
        select(Run)
        .where(Run.gpu == run.gpu, Run.id != run.id, Run.is_demo == run.is_demo)
        .order_by(Run.created_at.desc())
        .limit(MAX_PEERS)
    )
    same_gpu = []
    for other in candidates:
        values = figures(other)
        if values["application"] == own["application"]:
            same_gpu.append((other.cpu, values))
    groups = [("Same graphics card and game", [v for _, v in same_gpu])]
    same_cpu = [v for cpu, v in same_gpu if run.cpu and cpu == run.cpu]
    if len(same_cpu) >= MIN_PEERS:
        if len(same_cpu) == len(same_gpu):
            groups = []  # the same runs: one table, the more specific title
        groups.insert(0, ("Same CPU, graphics card and game", same_cpu))
    for title, rows in groups:
        group: dict[str, Any] = {"title": title, "runs": len(rows)}
        if len(rows) >= MIN_PEERS:
            group.update(_rank(rows, own))
        else:
            group["metrics"] = []
        answer["groups"].append(group)
    if not any(group["metrics"] for group in answer["groups"]):
        answer["reason"] = (
            f"Fewer than {MIN_PEERS} other runs of this graphics card in this game, "
            "so there is nothing fair to compare with yet."
        )
    return answer
