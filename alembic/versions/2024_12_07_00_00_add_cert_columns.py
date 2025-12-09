"""add_certificate_issuer_and_subject

Revision ID: 2024_12_07_00_00_add_cert_columns
Revises: 9188ee2f20e6
Create Date: 2024-12-07 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '2024_12_07_00_00_add_cert_columns'
down_revision = '9188ee2f20e6'
branch_labels = None
depends_on = None


def _has_column(inspector, table, column):
    """Check if column exists in table"""
    return column in [c["name"] for c in inspector.get_columns(table)]


def upgrade() -> None:
    # Add issuer and subject columns to certificates table (idempotent)
    bind = op.get_bind()
    inspector = inspect(bind)
    
    if not _has_column(inspector, 'certificates', 'issuer'):
        op.add_column('certificates', sa.Column('issuer', sa.String(length=500), nullable=True))
    
    if not _has_column(inspector, 'certificates', 'subject'):
        op.add_column('certificates', sa.Column('subject', sa.String(length=500), nullable=True))


def downgrade() -> None:
    # Remove columns (idempotent)
    bind = op.get_bind()
    inspector = inspect(bind)
    
    if _has_column(inspector, 'certificates', 'subject'):
        op.drop_column('certificates', 'subject')
    
    if _has_column(inspector, 'certificates', 'issuer'):
        op.drop_column('certificates', 'issuer')

