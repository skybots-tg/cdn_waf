"""add_certificate_issuer_and_subject

Revision ID: 8a9b2c3d4e5f
Revises: 
Create Date: 2024-12-07 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8a9b2c3d4e5f'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add issuer and subject columns to certificates table
    op.add_column('certificates', sa.Column('issuer', sa.String(length=500), nullable=True))
    op.add_column('certificates', sa.Column('subject', sa.String(length=500), nullable=True))


def downgrade() -> None:
    # Remove columns
    op.drop_column('certificates', 'subject')
    op.drop_column('certificates', 'issuer')

