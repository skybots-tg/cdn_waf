"""Add disabled_until column to origins table.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "origins",
        sa.Column("disabled_until", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_column("origins", "disabled_until")
