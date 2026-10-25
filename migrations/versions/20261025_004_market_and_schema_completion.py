"""Complete the README section 9 schema: market data, macro, FPI, constituents, predictions, sealed ledger.

* ``prices_daily`` gains the provenance columns every sourced table carries (README section 3, rule 3).
* New tables ``index_daily`` (official index closes), ``macro``, ``fpi_flows``, ``index_constituents``,
  ``predictions`` and ``sealed_ledger``. Every table loaded from a CSV has a unique natural key so the
  loaders can upsert.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-10-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("prices_daily") as batch:
        batch.add_column(sa.Column("source", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("source_url", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("fetched_at", sa.DateTime(), nullable=True))

    op.create_table(
        "index_daily",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("index_name", sa.String(length=128), nullable=False),
        sa.Column("ticker", sa.String(length=64), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("close", sa.Float(), nullable=True),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=128), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("index_name", "date", name="uq_index_daily_index_date"),
    )

    op.create_table(
        "macro",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("series", sa.String(length=64), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=128), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("series", "date", name="uq_macro_series_date"),
    )

    # equity_cr / debt_cr are NSDL net investment flows; aum_cr is the equity AUM at period end.
    op.create_table(
        "fpi_flows",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("nsdl_sector", sa.String(length=128), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("equity_cr", sa.Float(), nullable=True),
        sa.Column("debt_cr", sa.Float(), nullable=True),
        sa.Column("aum_cr", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=128), nullable=True),
        sa.Column("source_url", sa.String(length=512), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("nsdl_sector", "period_end", name="uq_fpi_flows_sector_period"),
    )

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

    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("entity", sa.String(length=64), nullable=False),
        sa.Column("budget_id", sa.String(length=64), nullable=False),
        sa.Column("expected_excess", sa.Float(), nullable=True),
        sa.Column("p10", sa.Float(), nullable=True),
        sa.Column("p90", sa.Float(), nullable=True),
        sa.Column("p_beat", sa.Float(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("top_reasons", sa.Text(), nullable=True),
        sa.UniqueConstraint("model_version", "entity", "budget_id", name="uq_predictions_key"),
    )

    op.create_table(
        "sealed_ledger",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("budget_id", sa.String(length=64), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("sealed_at", sa.DateTime(), nullable=False),
        sa.Column("commit_url", sa.String(length=512), nullable=True),
        sa.UniqueConstraint("budget_id", "file_sha256", name="uq_sealed_ledger_key"),
    )


def downgrade() -> None:
    for table in ("sealed_ledger", "predictions", "index_constituents", "fpi_flows", "macro", "index_daily"):
        op.drop_table(table)
    with op.batch_alter_table("prices_daily") as batch:
        batch.drop_column("fetched_at")
        batch.drop_column("source_url")
        batch.drop_column("source")
