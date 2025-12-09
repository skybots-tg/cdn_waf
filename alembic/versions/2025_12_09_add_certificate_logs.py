"""Add certificate_logs table for tracking SSL issuance process

Revision ID: 2025_12_09_add_cert_logs
Revises: 2024_12_08_00_01_sync_schema
Create Date: 2025-12-09

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '2025_12_09_add_cert_logs'
down_revision = '2024_12_08_00_01_sync_schema'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    
    # Check if table already exists
    if 'certificate_logs' not in inspector.get_table_names():
        op.create_table(
            'certificate_logs',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('certificate_id', sa.Integer(), nullable=False),
            sa.Column('level', sa.Enum('info', 'warning', 'error', 'success', name='certificateloglevel'), nullable=False),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('details', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.ForeignKeyConstraint(['certificate_id'], ['certificates.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_certificate_logs_certificate_id', 'certificate_logs', ['certificate_id'])


def downgrade():
    op.drop_index('ix_certificate_logs_certificate_id', table_name='certificate_logs')
    op.drop_table('certificate_logs')
    # Note: Enum type will remain in PostgreSQL, manual cleanup may be needed

