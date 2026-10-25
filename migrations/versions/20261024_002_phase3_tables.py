"""Add Phase 3 tables: features, targets and event study.

Revision ID: a1b2c3d4e5f6
Revises: f3d0f7f4f77d
Create Date: 2026-10-24 23:45:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "f3d0f7f4f77d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "features_sector_year",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sector_id", sa.String(length=64), nullable=False),
        sa.Column("budget_id", sa.String(length=64), nullable=False),
        sa.Column("feature_name", sa.String(length=128), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
    )
    op.create_index(
        "ix_features_sector_year_sector_budget_feature",
        "features_sector_year",
        ["sector_id", "budget_id", "feature_name"],
        unique=True,
    )
    op.create_index("ix_features_sector_year_budget_id", "features_sector_year", ["budget_id"])

    op.create_table(
        "features_stock_year",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("budget_id", sa.String(length=64), nullable=False),
        sa.Column("feature_name", sa.String(length=128), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
    )
    op.create_index(
        "ix_features_stock_year_symbol_budget_feature",
        "features_stock_year",
        ["symbol", "budget_id", "feature_name"],
        unique=True,
    )
    op.create_index("ix_features_stock_year_budget_id", "features_stock_year", ["budget_id"])

    op.create_table(
        "targets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("entity", sa.String(length=64), nullable=False),
        sa.Column("budget_id", sa.String(length=64), nullable=False),
        sa.Column("horizon", sa.String(length=32), nullable=False),
        sa.Column("excess_return", sa.Float(), nullable=True),
        sa.Column("target_complete", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index(
        "ix_targets_entity_budget_horizon",
        "targets",
        ["entity", "budget_id", "horizon"],
        unique=True,
    )

    op.create_table(
        "event_study",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("entity", sa.String(length=64), nullable=False),
        sa.Column("budget_id", sa.String(length=64), nullable=False),
        sa.Column("window", sa.String(length=32), nullable=False),
        sa.Column("car", sa.Float(), nullable=True),
        sa.Column("t_stat", sa.Float(), nullable=True),
        sa.Column("alpha", sa.Float(), nullable=True),
        sa.Column("beta", sa.Float(), nullable=True),
    )
    op.create_index(
        "ix_event_study_entity_budget_window",
        "event_study",
        ["entity", "budget_id", "window"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_event_study_entity_budget_window", table_name="event_study")
    op.drop_table("event_study")
    op.drop_index("ix_targets_entity_budget_horizon", table_name="targets")
    op.drop_table("targets")
    op.drop_index("ix_features_stock_year_budget_id", table_name="features_stock_year")
    op.drop_index("ix_features_stock_year_symbol_budget_feature", table_name="features_stock_year")
    op.drop_table("features_stock_year")
    op.drop_index("ix_features_sector_year_budget_id", table_name="features_sector_year")
    op.drop_index("ix_features_sector_year_sector_budget_feature", table_name="features_sector_year")
    op.drop_table("features_sector_year")
