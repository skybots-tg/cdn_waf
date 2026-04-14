"""Add completed_by_nodes column to cache_purges table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "cache_purges",
        sa.Column("completed_by_nodes", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("cache_purges", "completed_by_nodes")
