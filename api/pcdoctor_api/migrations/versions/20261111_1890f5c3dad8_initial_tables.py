"""Initial tables: runs, findings, work_log.

Revision ID: 1890f5c3dad8
Revises:
Create Date: 2026-11-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "1890f5c3dad8"
down_revision = None
branch_labels = None
depends_on = None


def json_type() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def timestamp() -> sa.types.TypeEngine:
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", timestamp(), nullable=False),
        sa.Column("captured_at", timestamp(), nullable=True),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("collector_version", sa.String(length=40), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("file_name", sa.String(length=80), nullable=False),
        sa.Column("file_bytes", sa.Integer(), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("verdict", sa.String(length=10), nullable=False),
        sa.Column("headline", sa.String(length=300), nullable=False),
        sa.Column("critical_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("info_count", sa.Integer(), nullable=False),
        sa.Column("cpu", sa.String(length=200), nullable=True),
        sa.Column("gpu", sa.String(length=200), nullable=True),
        sa.Column("ram_gb", sa.Integer(), nullable=True),
        sa.Column("avg_fps", sa.Float(), nullable=True),
        sa.Column("fps_1pct_low", sa.Float(), nullable=True),
        sa.Column("rules_version", sa.String(length=20), nullable=False),
        sa.Column("result", json_type(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_hash"),
    )
    op.create_index("ix_runs_created_at", "runs", ["created_at"])
    op.create_index("ix_runs_verdict", "runs", ["verdict"])

    op.create_table(
        "findings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("next_checks", json_type(), nullable=False),
        sa.Column("evidence", json_type(), nullable=False),
        sa.Column("error_codes", json_type(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_findings_category", "findings", ["category"])
    op.create_index("ix_findings_code", "findings", ["code"])
    op.create_index("ix_findings_run_position", "findings", ["run_id", "position"])

    op.create_table(
        "work_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", timestamp(), nullable=False),
        sa.Column("updated_at", timestamp(), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("device_type", sa.String(length=20), nullable=False),
        sa.Column("device", sa.String(length=300), nullable=False),
        sa.Column("symptoms", sa.Text(), nullable=False),
        sa.Column("steps", sa.Text(), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=False),
        sa.Column("fix", sa.Text(), nullable=False),
        sa.Column("components", json_type(), nullable=False),
        sa.Column("error_codes", json_type(), nullable=False),
        sa.Column("reference", sa.String(length=80), nullable=False),
        sa.Column("minutes_spent", sa.Integer(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_work_log_category", "work_log", ["category"])
    op.create_index("ix_work_log_occurred_on", "work_log", ["occurred_on"])
    op.create_index("ix_work_log_run_id", "work_log", ["run_id"])
    op.create_index("ix_work_log_status", "work_log", ["status"])


def downgrade() -> None:
    op.drop_table("work_log")
    op.drop_table("findings")
    op.drop_table("runs")
