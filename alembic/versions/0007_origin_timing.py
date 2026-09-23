"""Время ответа origin, его статус и размер запроса в логах и сводах.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-23

До сих пор было одно время — сколько запрос провёл на ноде целиком, вместе с
ожиданием origin. Понять, тормозит сайт или CDN, по нему нельзя. Нода теперь
пишет $upstream_response_time, $upstream_status и $request_length.
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_STATS = ("analytics_hourly_stats", "analytics_daily_stats")


def upgrade():
    op.add_column("request_logs", sa.Column("upstream_time", sa.Integer(), nullable=True))
    op.add_column("request_logs", sa.Column("upstream_status", sa.SmallInteger(), nullable=True))
    op.add_column("request_logs", sa.Column("bytes_received", sa.BigInteger(), nullable=True))
    for table in _STATS:
        op.add_column(
            table,
            sa.Column("origin_requests", sa.Integer(), nullable=False, server_default="0"),
        )
        op.add_column(
            table,
            sa.Column("avg_origin_time", sa.Float(), nullable=False, server_default="0"),
        )


def downgrade():
    for table in _STATS:
        op.drop_column(table, "avg_origin_time")
        op.drop_column(table, "origin_requests")
    op.drop_column("request_logs", "bytes_received")
    op.drop_column("request_logs", "upstream_status")
    op.drop_column("request_logs", "upstream_time")
