"""Fix edge_node_id foreign key constraint to use SET NULL on delete

Revision ID: 2026_02_04_fix_edge_fk
Revises: 2025_12_09_fix_cert_enum
Create Date: 2026-02-04

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '2026_02_04_fix_edge_fk'
down_revision = '2025_12_09_fix_cert_enum'
branch_labels = None
depends_on = None


def upgrade():
    # Drop the old foreign key constraint and create a new one with ON DELETE SET NULL
    # The constraint name may vary; find it dynamically
    
    # First, try to drop any existing constraint
    op.execute("""
        DO $$ 
        DECLARE 
            r RECORD;
        BEGIN 
            FOR r IN (
                SELECT conname 
                FROM pg_constraint 
                WHERE conrelid = 'request_logs'::regclass 
                AND confrelid = 'edge_nodes'::regclass
            ) LOOP
                EXECUTE 'ALTER TABLE request_logs DROP CONSTRAINT ' || quote_ident(r.conname);
            END LOOP;
        END $$;
    """)
    
    # Add the new constraint with ON DELETE SET NULL
    op.create_foreign_key(
        'fk_request_logs_edge_node_id',
        'request_logs',
        'edge_nodes',
        ['edge_node_id'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade():
    # Drop the new constraint
    op.drop_constraint('fk_request_logs_edge_node_id', 'request_logs', type_='foreignkey')
    
    # Recreate without ON DELETE behavior
    op.create_foreign_key(
        'request_logs_edge_node_id_fkey',
        'request_logs',
        'edge_nodes',
        ['edge_node_id'],
        ['id']
    )
