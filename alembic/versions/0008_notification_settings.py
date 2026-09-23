"""Настройки уведомлений: какие оповещения слать и куда ещё (вебхуки).

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-23

Вкладка «Notifications» в настройках панели показывала переключатели, но
ничего не сохраняла: кнопка отвечала «saved», а оповещения о сертификатах,
атаках, квотах и еженедельные отчёты не существовали вовсе.
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notification_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("security", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("downtime", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ssl", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("usage", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("weekly", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("webhooks", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table("notification_settings")
