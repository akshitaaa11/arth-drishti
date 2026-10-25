"""Widen budget_lines.stage: PRS labels such as 'Provisional Actual' exceed 16 characters.

SQLite does not enforce VARCHAR lengths, so only Postgres rejected the longer values.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("budget_lines") as batch:
        batch.alter_column("stage", existing_type=sa.String(length=16), type_=sa.String(length=32), existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("budget_lines") as batch:
        batch.alter_column("stage", existing_type=sa.String(length=32), type_=sa.String(length=16), existing_nullable=False)
