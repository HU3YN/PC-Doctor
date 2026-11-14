"""A run can have several private links: one per guest upload.

Before, a second upload of the same file replaced the run's only key, which
broke the first uploader's link. Existing keys move to the new table.

Revision ID: 4d2e8a1b6c37
Revises: 7a3c1e5b9d20
Create Date: 2026-11-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "4d2e8a1b6c37"
down_revision = "7a3c1e5b9d20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "share_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index("ix_share_keys_run_id", "share_keys", ["run_id"], unique=False)
    op.execute(
        "INSERT INTO share_keys (run_id, key_hash, label, created_at) "
        "SELECT id, share_hash, label, created_at FROM runs WHERE share_hash IS NOT NULL"
    )
    with op.batch_alter_table("runs") as batch:
        batch.drop_constraint("uq_runs_share_hash", type_="unique")
        batch.drop_column("share_hash")


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("share_hash", sa.String(length=64), nullable=True))
        batch.create_unique_constraint("uq_runs_share_hash", ["share_hash"])
    # Keep the newest key of each run; the others stop working.
    op.execute(
        "UPDATE runs SET share_hash = (SELECT key_hash FROM share_keys "
        "WHERE share_keys.run_id = runs.id ORDER BY share_keys.id DESC LIMIT 1)"
    )
    op.drop_index("ix_share_keys_run_id", table_name="share_keys")
    op.drop_table("share_keys")
