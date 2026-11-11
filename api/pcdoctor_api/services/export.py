"""Export and import the work log, so the notes are never trapped in one database."""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Any

from pcdoctor_analysis.model import CATEGORIES

from ..models import WorkLogEntry
from ..schemas import DEVICE_TYPES, STATUSES

EXPORT_FIELDS = [
    "occurred_on",
    "title",
    "status",
    "category",
    "device_type",
    "device",
    "symptoms",
    "steps",
    "root_cause",
    "fix",
    "components",
    "error_codes",
    "reference",
    "minutes_spent",
]


def entry_to_dict(entry: WorkLogEntry) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for name in EXPORT_FIELDS:
        value = getattr(entry, name)
        data[name] = value.isoformat() if isinstance(value, date) else value
    return data


def to_json(entries: list[WorkLogEntry]) -> dict[str, Any]:
    return {
        "format": "pcdoctor-worklog",
        "version": 1,
        "entries": [entry_to_dict(e) for e in entries],
    }


def to_csv(entries: list[WorkLogEntry]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=EXPORT_FIELDS, lineterminator="\n")
    writer.writeheader()
    for entry in entries:
        row = entry_to_dict(entry)
        row["components"] = "; ".join(row["components"] or [])
        row["error_codes"] = "; ".join(row["error_codes"] or [])
        # A cell starting with = + - @ can run as a formula when the file is
        # opened in a spreadsheet; a leading apostrophe makes it plain text.
        for key, value in row.items():
            if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
                row[key] = "'" + value
        writer.writerow(row)
    return out.getvalue()


def to_markdown(entries: list[WorkLogEntry]) -> str:
    lines = ["# PC Doctor work log", "", f"{len(entries)} entries.", ""]
    for entry in entries:
        lines.append(f"## {entry.occurred_on.isoformat()} - {entry.title}")
        lines.append("")
        facts = [
            STATUSES.get(entry.status, entry.status).split(" - ")[0],
            CATEGORIES.get(entry.category, entry.category),
            DEVICE_TYPES.get(entry.device_type, entry.device_type),
        ]
        if entry.device:
            facts.append(entry.device)
        if entry.minutes_spent:
            facts.append(f"{entry.minutes_spent} min")
        lines.append(" | ".join(facts))
        lines.append("")
        if entry.error_codes:
            lines += ["**Codes:** " + ", ".join(entry.error_codes), ""]
        if entry.components:
            lines += ["**Parts:** " + ", ".join(entry.components), ""]
        for heading, text in (
            ("Symptoms", entry.symptoms),
            ("What I checked", entry.steps),
            ("Root cause", entry.root_cause),
            ("Fix", entry.fix),
        ):
            if text:
                lines += [f"**{heading}**", "", text, ""]
    return "\n".join(lines).rstrip() + "\n"
