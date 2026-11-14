"""At most one master account, enforced by the database.

Two set-up requests at the same moment could otherwise both create one.

Revision ID: 9b1f3c7e2a54
Revises: 4d2e8a1b6c37
Create Date: 2026-11-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "9b1f3c7e2a54"
down_revision = "4d2e8a1b6c37"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_accounts_one_master",
        "accounts",
        ["role"],
        unique=True,
        sqlite_where=sa.text("role = 'master'"),
        postgresql_where=sa.text("role = 'master'"),
    )


def downgrade() -> None:
    op.drop_index("uq_accounts_one_master", table_name="accounts")
