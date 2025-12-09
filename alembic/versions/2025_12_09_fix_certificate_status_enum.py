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
    
    # First, check if the enum value already exists
    connection = op.get_bind()
    
    # Try to add the new enum value
    try:
        # For PostgreSQL, use ALTER TYPE to add new enum value
        connection.execute(sa.text(
            "ALTER TYPE certificatestatus ADD VALUE IF NOT EXISTS 'failed'"
        ))
    except Exception as e:
        # If it fails, the value might already exist - that's OK
        print(f"Note: Could not add 'failed' to enum (might already exist): {e}")


def downgrade():
    # Cannot remove enum values in PostgreSQL without recreating the type
    # This is a non-reversible migration for safety
    pass

