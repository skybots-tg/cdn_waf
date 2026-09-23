"""Своды аналитики: байты из кэша, ограничения частоты; логи удаляются с доменом.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-23

* cached_bytes — сколько трафика отдано из кэша ноды («сэкономлено» в разделе
  CDN). Раньше «экономию» считали как трафик × долю кэша, то есть наугад.
* rate_limited — ответы 429 от правил ограничения частоты. WAF их не
  помечает, и в «угрозах» они не видны.
* request_logs.domain_id — ON DELETE CASCADE: без него удаление домена
  поднимало в память все его логи, чтобы проставить им NULL.
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_TABLES = ("analytics_hourly_stats", "analytics_daily_stats")


def upgrade():
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("cached_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        )
        op.add_column(
            table,
            sa.Column("rate_limited", sa.Integer(), nullable=False, server_default="0"),
        )
    op.drop_constraint("request_logs_domain_id_fkey", "request_logs", type_="foreignkey")
    op.create_foreign_key(
        "request_logs_domain_id_fkey", "request_logs", "domains",
        ["domain_id"], ["id"], ondelete="CASCADE",
    )


def downgrade():
    op.drop_constraint("request_logs_domain_id_fkey", "request_logs", type_="foreignkey")
    op.create_foreign_key(
        "request_logs_domain_id_fkey", "request_logs", "domains", ["domain_id"], ["id"],
    )
    for table in _TABLES:
        op.drop_column(table, "rate_limited")
        op.drop_column(table, "cached_bytes")
