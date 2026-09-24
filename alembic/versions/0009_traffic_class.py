"""Класс трафика и сеть клиента в сырых логах.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-24

Аналитика делила трафик только по User-Agent, и боты с браузерным UA
считались людьми. Теперь у строки есть класс (app/services/traffic_class.py)
и номер AS клиента. Старые строки размечает scripts/classify_traffic.py.
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("request_logs", sa.Column("asn", sa.Integer(), nullable=True))
    op.add_column("request_logs", sa.Column("client_class", sa.String(length=10), nullable=True))


def downgrade():
    op.drop_column("request_logs", "client_class")
    op.drop_column("request_logs", "asn")
