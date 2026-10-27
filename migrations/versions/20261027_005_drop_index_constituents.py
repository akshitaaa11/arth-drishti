"""Drop ``index_constituents``: the Nifty 500 point-in-time constituent work was removed.

The universe is now a listing-date plus liquidity rule computed from prices (README ground rule 1), so no table
holds index membership. The table was created empty-by-design in migration 004 and never held trusted data. The
downgrade recreates it exactly as 004 defined it. Migrations 001-004 are unchanged.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-10-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("index_constituents")


def downgrade() -> None:
    op.create_table(
        "index_constituents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("index_name", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=256), nullable=True),
        sa.Column("source_url", sa.String(length=512), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("index_name", "symbol", "effective_from", name="uq_index_constituents_key"),
    )
