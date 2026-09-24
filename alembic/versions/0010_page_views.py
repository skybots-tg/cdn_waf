"""Просмотры страниц в почасовом и суточном своде.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-24

Экраны показывали только запросы: одна страница — это десятки запросов за
CSS, JS и картинками, и по ним не понять, сколько страниц посмотрели.
Прошедшие часы за 30 дней пересчитывает analytics_aggregation.backfill.
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_STATS = ("analytics_hourly_stats", "analytics_daily_stats")


def upgrade():
    for table in _STATS:
        op.add_column(
            table,
            sa.Column("page_views", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade():
    for table in _STATS:
        op.drop_column(table, "page_views")
