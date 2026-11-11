"""Database tables.

runs       one uploaded collector run and its analysis result
findings   what the rules engine found in a run (one row per finding)
work_log   the technician's own notes: symptom, cause, fix
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, UTCDateTime, utcnow

# JSONB on PostgreSQL (indexable, compact), plain JSON elsewhere.
JsonType = JSON().with_variant(JSONB(), "postgresql")


def new_id() -> str:
    return uuid.uuid4().hex


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    # When the collector ran, from its manifest (None if the manifest is missing).
    captured_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    label: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[str] = mapped_column(String(20), default="")  # "quick" | "capture" | ""
    collector_version: Mapped[str] = mapped_column(String(40), default="")
    # SHA-256 of the uploaded file: uploading the same run twice returns the
    # first one instead of making a duplicate.
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    file_name: Mapped[str] = mapped_column(String(80))  # under the runs folder
    file_bytes: Mapped[int] = mapped_column(Integer, default=0)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    # A summary, copied out of the result so lists do not load the big JSON.
    verdict: Mapped[str] = mapped_column(String(10), default="ok", index=True)
    headline: Mapped[str] = mapped_column(String(300), default="")
    critical_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    info_count: Mapped[int] = mapped_column(Integer, default=0)
    cpu: Mapped[str | None] = mapped_column(String(200))
    gpu: Mapped[str | None] = mapped_column(String(200))
    ram_gb: Mapped[int | None] = mapped_column(Integer)
    avg_fps: Mapped[float | None] = mapped_column(Float)
    fps_1pct_low: Mapped[float | None] = mapped_column(Float)
    rules_version: Mapped[str] = mapped_column(String(20), default="")
    # Everything else from the analysis: device, checks, statistics, chart
    # series, notes. Findings live in their own table.
    result: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)

    findings: Mapped[list[Finding]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="Finding.position",
        passive_deletes=True,
    )
    work_log_entries: Mapped[list[WorkLogEntry]] = relationship(back_populates="run")


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)  # order within the run, worst first
    code: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text)
    next_checks: Mapped[list[str]] = mapped_column(JsonType, default=list)
    evidence: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    error_codes: Mapped[list[str]] = mapped_column(JsonType, default=list)

    run: Mapped[Run] = relationship(back_populates="findings")

    __table_args__ = (Index("ix_findings_run_position", "run_id", "position"),)


class WorkLogEntry(Base):
    __tablename__ = "work_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    occurred_on: Mapped[date] = mapped_column(Date, index=True)  # the day of the job
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    category: Mapped[str] = mapped_column(String(32), default="other", index=True)
    device_type: Mapped[str] = mapped_column(String(20), default="other")
    device: Mapped[str] = mapped_column(String(300), default="")  # the build, never the owner
    symptoms: Mapped[str] = mapped_column(Text, default="")
    steps: Mapped[str] = mapped_column(Text, default="")  # what was checked or tried
    root_cause: Mapped[str] = mapped_column(Text, default="")
    fix: Mapped[str] = mapped_column(Text, default="")
    components: Mapped[list[str]] = mapped_column(JsonType, default=list)  # parts involved
    error_codes: Mapped[list[str]] = mapped_column(JsonType, default=list)
    reference: Mapped[str] = mapped_column(String(80), default="")  # own job number
    minutes_spent: Mapped[int | None] = mapped_column(Integer)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    # The run this job was diagnosed from. Deleting the run keeps the entry.
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), index=True
    )

    run: Mapped[Run | None] = relationship(back_populates="work_log_entries")
