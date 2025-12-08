"""add_certificate_issuer_and_subject

Revision ID: 2024_12_07_00_00_add_cert_columns
Revises: 9188ee2f20e6
Create Date: 2024-12-07 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2024_12_07_00_00_add_cert_columns'
down_revision = '9188ee2f20e6'
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

