"""Member accounts, Discord/Google identities, and who uploaded a run.

Revision ID: 7a3c1e5b9d20
Revises: cf8909d36705
Create Date: 2026-11-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "7a3c1e5b9d20"
down_revision = "cf8909d36705"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("subject", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "subject", name="uq_identity"),
    )
    # Every account that exists so far is the master.
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(
            sa.Column("role", sa.String(length=10), server_default="master", nullable=False)
        )
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("owner_id", sa.Integer(), nullable=True))
        batch.create_index("ix_runs_owner_id", ["owner_id"], unique=False)
        batch.create_foreign_key(
            "fk_runs_owner_id_accounts", "accounts", ["owner_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.drop_constraint("fk_runs_owner_id_accounts", type_="foreignkey")
        batch.drop_index("ix_runs_owner_id")
        batch.drop_column("owner_id")
    with op.batch_alter_table("accounts") as batch:
        batch.drop_column("role")
    op.drop_table("identities")
