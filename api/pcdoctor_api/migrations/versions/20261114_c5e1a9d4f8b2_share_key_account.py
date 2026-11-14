"""Which member account made each private link.

A member who uploads a file that is already stored gets a link but not the
run; recording the account on the link lets "My runs" list it anyway.

Revision ID: c5e1a9d4f8b2
Revises: 9b1f3c7e2a54
Create Date: 2026-11-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c5e1a9d4f8b2"
down_revision = "9b1f3c7e2a54"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("share_keys") as batch:
        batch.add_column(sa.Column("account_id", sa.Integer(), nullable=True))
        batch.create_index("ix_share_keys_account_id", ["account_id"], unique=False)
        batch.create_foreign_key(
            "fk_share_keys_account_id_accounts",
            "accounts",
            ["account_id"],
            ["id"],
            ondelete="SET NULL",
        )
    # Until now only the first upload of a run could have a member as owner:
    # give that run's first link to its owner.
    op.execute(
        "UPDATE share_keys SET account_id = "
        "(SELECT owner_id FROM runs WHERE runs.id = share_keys.run_id) "
        "WHERE id IN (SELECT MIN(id) FROM share_keys GROUP BY run_id)"
    )


def downgrade() -> None:
    with op.batch_alter_table("share_keys") as batch:
        batch.drop_constraint("fk_share_keys_account_id_accounts", type_="foreignkey")
        batch.drop_index("ix_share_keys_account_id")
        batch.drop_column("account_id")
