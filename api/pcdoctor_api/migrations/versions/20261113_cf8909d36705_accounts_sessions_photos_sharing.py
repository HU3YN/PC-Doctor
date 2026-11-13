"""Accounts, sign-in sessions, the photo inbox, and private links to guest runs.

Revision ID: cf8909d36705
Revises: 1890f5c3dad8
Create Date: 2026-11-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "cf8909d36705"
down_revision = "1890f5c3dad8"
branch_labels = None
depends_on = None


def json_type() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def timestamp() -> sa.types.TypeEngine:
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", timestamp(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("created_at", timestamp(), nullable=False),
        sa.Column("expires_at", timestamp(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_table(
        "photo_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("created_at", timestamp(), nullable=False),
        sa.Column("expires_at", timestamp(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_table(
        "photos",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", timestamp(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("file_name", sa.String(length=80), nullable=False),
        sa.Column("file_bytes", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("reading", json_type(), nullable=False),
        sa.Column("ai", json_type(), nullable=True),
        sa.Column("work_log_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["work_log_id"], ["work_log.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_photos_created_at", "photos", ["created_at"])

    # Batch mode: SQLite cannot add a constraint to an existing table directly.
    with op.batch_alter_table("runs") as batch:
        batch.add_column(
            sa.Column("source", sa.String(length=10), nullable=False, server_default="master")
        )
        batch.add_column(sa.Column("share_hash", sa.String(length=64), nullable=True))
        batch.create_unique_constraint("uq_runs_share_hash", ["share_hash"])


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.drop_constraint("uq_runs_share_hash", type_="unique")
        batch.drop_column("share_hash")
        batch.drop_column("source")
    op.drop_index("ix_photos_created_at", table_name="photos")
    op.drop_table("photos")
    op.drop_table("photo_links")
    op.drop_table("sessions")
    op.drop_table("accounts")
