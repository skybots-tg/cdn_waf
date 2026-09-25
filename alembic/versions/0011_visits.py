"""Визиты в почасовом и суточном своде.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-25

Визит — как в Яндекс Метрике: просмотры одного посетителя (IP и
User-Agent), пока между ними меньше 30 минут. Считается в часе, где начался,
поэтому складывается из часов, как запросы. Прошедшие часы за 30 дней
пересчитывает analytics_aggregation.backfill.
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_STATS = ("analytics_hourly_stats", "analytics_daily_stats")


def upgrade():
    for table in _STATS:
        op.add_column(
            table,
            sa.Column("visits", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade():
    for table in _STATS:
        op.drop_column(table, "visits")
