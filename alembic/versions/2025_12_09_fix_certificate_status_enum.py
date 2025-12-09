"""Fix certificate status enum - add 'failed' value

Revision ID: 2025_12_09_fix_cert_enum
Revises: 2025_12_09_add_cert_logs
Create Date: 2025-12-09

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '2025_12_09_fix_cert_enum'
down_revision = '2025_12_09_add_cert_logs'
branch_labels = None
depends_on = None


def upgrade():
    # Add 'failed' value to certificatestatus enum if not exists
    # PostgreSQL requires special handling for enum types
    
    # Use execute with proper isolation level for ALTER TYPE
    # This needs to be done outside of a transaction
    with op.get_context().autocommit_block():
        op.execute(
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_enum e "
            "JOIN pg_type t ON e.enumtypid = t.oid "
            "WHERE t.typname = 'certificatestatus' AND e.enumlabel = 'failed') THEN "
            "ALTER TYPE certificatestatus ADD VALUE 'failed'; "
            "END IF; "
            "END $$;"
        )


def downgrade():
    # Cannot remove enum values in PostgreSQL without recreating the type
    # This is a non-reversible migration for safety
    pass

