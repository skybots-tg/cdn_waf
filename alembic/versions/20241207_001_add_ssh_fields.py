"""add ssh fields

Revision ID: 001
Revises: 
Create Date: 2024-12-07 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    table_names = inspector.get_table_names()
    
    # Update edge_nodes
    if 'edge_nodes' in table_names:
        columns = [c['name'] for c in inspector.get_columns('edge_nodes')]
        if 'ssh_host' not in columns:
            op.add_column('edge_nodes', sa.Column('ssh_host', sa.String(255), nullable=True))
        if 'ssh_port' not in columns:
            op.add_column('edge_nodes', sa.Column('ssh_port', sa.Integer(), nullable=True, server_default='22'))
        if 'ssh_user' not in columns:
            op.add_column('edge_nodes', sa.Column('ssh_user', sa.String(255), nullable=True))
        if 'ssh_key' not in columns:
            op.add_column('edge_nodes', sa.Column('ssh_key', sa.Text(), nullable=True))
        if 'ssh_password' not in columns:
            op.add_column('edge_nodes', sa.Column('ssh_password', sa.String(255), nullable=True))

    # Update dns_nodes
    if 'dns_nodes' in table_names:
        columns = [c['name'] for c in inspector.get_columns('dns_nodes')]
        if 'ssh_host' not in columns:
            op.add_column('dns_nodes', sa.Column('ssh_host', sa.String(255), nullable=True))
        if 'ssh_port' not in columns:
            op.add_column('dns_nodes', sa.Column('ssh_port', sa.Integer(), nullable=True, server_default='22'))
        if 'ssh_user' not in columns:
            op.add_column('dns_nodes', sa.Column('ssh_user', sa.String(255), nullable=True))
        if 'ssh_key' not in columns:
            op.add_column('dns_nodes', sa.Column('ssh_key', sa.Text(), nullable=True))
        if 'ssh_password' not in columns:
            op.add_column('dns_nodes', sa.Column('ssh_password', sa.String(255), nullable=True))

def downgrade() -> None:
    pass

