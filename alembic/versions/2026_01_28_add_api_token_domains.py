"""Add API token domains relationship

Revision ID: 2026012801
Revises: 2025_12_09_fix_certificate_status_enum
Create Date: 2026-01-28

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2026012801'
down_revision = '2025_12_09_fix_certificate_status_enum'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create many-to-many relationship table for API tokens and domains
    op.create_table(
        'api_token_domains',
        sa.Column('api_token_id', sa.Integer(), nullable=False),
        sa.Column('domain_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['api_token_id'], ['api_tokens.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['domain_id'], ['domains.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('api_token_id', 'domain_id')
    )
    
    # Create indexes for better query performance
    op.create_index('ix_api_token_domains_api_token_id', 'api_token_domains', ['api_token_id'])
    op.create_index('ix_api_token_domains_domain_id', 'api_token_domains', ['domain_id'])


def downgrade() -> None:
    op.drop_index('ix_api_token_domains_domain_id', 'api_token_domains')
    op.drop_index('ix_api_token_domains_api_token_id', 'api_token_domains')
    op.drop_table('api_token_domains')
