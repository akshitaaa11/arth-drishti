"""Initial schema for Arth Drishti.

Revision ID: f3d0f7f4f77d
Revises: 
Create Date: 2026-10-23 19:51:35.450000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f3d0f7f4f77d"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "budget_events",
        sa.Column("budget_id", sa.String(length=64), primary_key=True),
        sa.Column("fiscal_year", sa.String(length=32), nullable=False),
        sa.Column("presented_on", sa.Date, nullable=False),
        sa.Column("budget_type", sa.String(length=32), nullable=False),
        sa.Column("finance_minister", sa.String(length=128), nullable=True),
        sa.Column("is_interim", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_election_year", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text(), nullable=True),
    )

    op.create_table(
        "budget_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("fiscal_year", sa.String(length=32), nullable=False),
        sa.Column("line_type", sa.String(length=32), nullable=False),
        sa.Column("line_name", sa.String(length=256), nullable=False),
        sa.Column("canonical_name", sa.String(length=256), nullable=True),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("amount_cr", sa.Float(), nullable=True),
        sa.Column("capex_cr", sa.Float(), nullable=True),
        sa.Column("revenue_cr", sa.Float(), nullable=True),
        sa.Column("source_doc", sa.String(length=256), nullable=True),
        sa.Column("source_page", sa.String(length=64), nullable=True),
        sa.Column("source_url", sa.String(length=512), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
    )

    op.create_index("ix_budget_lines_fiscal_year", "budget_lines", ["fiscal_year"])
    op.create_index("ix_budget_lines_line_name", "budget_lines", ["line_name"])

    op.create_table(
        "sector_line_map",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sector_id", sa.String(length=64), nullable=False),
        sa.Column("canonical_name", sa.String(length=256), nullable=False),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )

    op.create_table(
        "stocks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=64), nullable=False, unique=True),
        sa.Column("sector_id", sa.String(length=64), nullable=True),
        sa.Column("listing_date", sa.Date(), nullable=True),
        sa.Column("delisting_date", sa.Date(), nullable=True),
        sa.Column("yahoo_symbol", sa.String(length=128), nullable=True),
    )

    op.create_table(
        "prices_daily",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open", sa.Float(), nullable=True),
        sa.Column("high", sa.Float(), nullable=True),
        sa.Column("low", sa.Float(), nullable=True),
        sa.Column("close", sa.Float(), nullable=True),
        sa.Column("adj_close", sa.Float(), nullable=True),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("traded_value_cr", sa.Float(), nullable=True),
    )
    op.create_index("ix_prices_daily_symbol_date", "prices_daily", ["symbol", "date"], unique=True)

    op.create_table(
        "fetch_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job", sa.String(length=128), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("rows", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("fetch_log")
    op.drop_index("ix_prices_daily_symbol_date", table_name="prices_daily")
    op.drop_table("prices_daily")
    op.drop_table("stocks")
    op.drop_table("sector_line_map")
    op.drop_index("ix_budget_lines_line_name", table_name="budget_lines")
    op.drop_index("ix_budget_lines_fiscal_year", table_name="budget_lines")
    op.drop_table("budget_lines")
    op.drop_table("budget_events")
