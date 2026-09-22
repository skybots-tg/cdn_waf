"""Add disabled_by column to edge_nodes table.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "edge_nodes",
        sa.Column("disabled_by", sa.String(10), nullable=True),
    )
    # Кто выключил уже выключенные ноды, по БД не понять: метка автоматики
    # жила в Redis сутки, а свежий heartbeat бывает и у ноды, выключенной
    # руками. Спорные считаем ручными: ошибка в эту сторону оставит ноду
    # выключенной до клика в панели, в обратную — вернёт в DNS ноду, которую
    # человек из ротации убрал.
    edge_nodes = sa.table(
        "edge_nodes",
        sa.column("enabled", sa.Boolean),
        sa.column("disabled_by", sa.String),
    )
    op.execute(
        edge_nodes.update()
        .where(edge_nodes.c.enabled == sa.false())
        .values(disabled_by="manual")
    )


def downgrade():
    op.drop_column("edge_nodes", "disabled_by")
