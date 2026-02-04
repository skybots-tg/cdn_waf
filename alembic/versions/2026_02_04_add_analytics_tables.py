"""Add analytics aggregation tables

Revision ID: add_analytics_tables
Revises: 2026_02_04_fix_edge_fk
Create Date: 2026-02-04 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_analytics_tables'
down_revision = '2026_02_04_fix_edge_fk'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create analytics_hourly_stats table
    op.create_table(
        'analytics_hourly_stats',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hour', sa.DateTime(), nullable=False),
        sa.Column('domain_id', sa.Integer(), nullable=True),
        sa.Column('edge_node_id', sa.Integer(), nullable=True),
        sa.Column('total_requests', sa.BigInteger(), default=0),
        sa.Column('total_bytes_sent', sa.BigInteger(), default=0),
        sa.Column('total_bytes_received', sa.BigInteger(), default=0),
        sa.Column('status_2xx', sa.Integer(), default=0),
        sa.Column('status_3xx', sa.Integer(), default=0),
        sa.Column('status_4xx', sa.Integer(), default=0),
        sa.Column('status_5xx', sa.Integer(), default=0),
        sa.Column('cache_hits', sa.Integer(), default=0),
        sa.Column('cache_misses', sa.Integer(), default=0),
        sa.Column('cache_bypass', sa.Integer(), default=0),
        sa.Column('waf_blocked', sa.Integer(), default=0),
        sa.Column('waf_challenged', sa.Integer(), default=0),
        sa.Column('avg_response_time', sa.Float(), default=0),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['domain_id'], ['domains.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['edge_node_id'], ['edge_nodes.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('hour', 'domain_id', 'edge_node_id', name='uq_hourly_stats')
    )
    op.create_index('ix_analytics_hourly_stats_id', 'analytics_hourly_stats', ['id'])
    op.create_index('ix_analytics_hourly_stats_hour', 'analytics_hourly_stats', ['hour'])
    op.create_index('ix_analytics_hourly_stats_domain_id', 'analytics_hourly_stats', ['domain_id'])
    op.create_index('ix_analytics_hourly_stats_edge_node_id', 'analytics_hourly_stats', ['edge_node_id'])
    op.create_index('ix_hourly_stats_hour_domain', 'analytics_hourly_stats', ['hour', 'domain_id'])

    # Create analytics_daily_stats table
    op.create_table(
        'analytics_daily_stats',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('domain_id', sa.Integer(), nullable=True),
        sa.Column('total_requests', sa.BigInteger(), default=0),
        sa.Column('total_bytes_sent', sa.BigInteger(), default=0),
        sa.Column('total_bytes_received', sa.BigInteger(), default=0),
        sa.Column('status_2xx', sa.Integer(), default=0),
        sa.Column('status_3xx', sa.Integer(), default=0),
        sa.Column('status_4xx', sa.Integer(), default=0),
        sa.Column('status_5xx', sa.Integer(), default=0),
        sa.Column('cache_hits', sa.Integer(), default=0),
        sa.Column('cache_misses', sa.Integer(), default=0),
        sa.Column('cache_bypass', sa.Integer(), default=0),
        sa.Column('waf_blocked', sa.Integer(), default=0),
        sa.Column('waf_challenged', sa.Integer(), default=0),
        sa.Column('avg_response_time', sa.Float(), default=0),
        sa.Column('peak_requests_hour', sa.Integer(), default=0),
        sa.Column('peak_bandwidth_hour', sa.BigInteger(), default=0),
        sa.Column('unique_visitors', sa.Integer(), default=0),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['domain_id'], ['domains.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('day', 'domain_id', name='uq_daily_stats')
    )
    op.create_index('ix_analytics_daily_stats_id', 'analytics_daily_stats', ['id'])
    op.create_index('ix_analytics_daily_stats_day', 'analytics_daily_stats', ['day'])
    op.create_index('ix_analytics_daily_stats_domain_id', 'analytics_daily_stats', ['domain_id'])
    op.create_index('ix_daily_stats_day_domain', 'analytics_daily_stats', ['day', 'domain_id'])

    # Create analytics_geo_stats table
    op.create_table(
        'analytics_geo_stats',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('domain_id', sa.Integer(), nullable=True),
        sa.Column('country_code', sa.String(2), nullable=False),
        sa.Column('total_requests', sa.BigInteger(), default=0),
        sa.Column('total_bytes_sent', sa.BigInteger(), default=0),
        sa.Column('unique_visitors', sa.Integer(), default=0),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['domain_id'], ['domains.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('day', 'domain_id', 'country_code', name='uq_geo_stats')
    )
    op.create_index('ix_analytics_geo_stats_id', 'analytics_geo_stats', ['id'])
    op.create_index('ix_analytics_geo_stats_day', 'analytics_geo_stats', ['day'])
    op.create_index('ix_analytics_geo_stats_domain_id', 'analytics_geo_stats', ['domain_id'])
    op.create_index('ix_analytics_geo_stats_country_code', 'analytics_geo_stats', ['country_code'])
    op.create_index('ix_geo_stats_day_domain_country', 'analytics_geo_stats', ['day', 'domain_id', 'country_code'])

    # Create analytics_top_paths table
    op.create_table(
        'analytics_top_paths',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('domain_id', sa.Integer(), nullable=False),
        sa.Column('path', sa.String(2048), nullable=False),
        sa.Column('total_requests', sa.BigInteger(), default=0),
        sa.Column('total_bytes_sent', sa.BigInteger(), default=0),
        sa.Column('cache_hits', sa.Integer(), default=0),
        sa.Column('cache_misses', sa.Integer(), default=0),
        sa.Column('status_2xx', sa.Integer(), default=0),
        sa.Column('status_4xx', sa.Integer(), default=0),
        sa.Column('status_5xx', sa.Integer(), default=0),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['domain_id'], ['domains.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('day', 'domain_id', 'path', name='uq_top_paths')
    )
    op.create_index('ix_analytics_top_paths_id', 'analytics_top_paths', ['id'])
    op.create_index('ix_analytics_top_paths_day', 'analytics_top_paths', ['day'])
    op.create_index('ix_analytics_top_paths_domain_id', 'analytics_top_paths', ['domain_id'])
    op.create_index('ix_top_paths_day_domain', 'analytics_top_paths', ['day', 'domain_id'])

    # Create analytics_error_stats table
    op.create_table(
        'analytics_error_stats',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('domain_id', sa.Integer(), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=False),
        sa.Column('path', sa.String(2048), nullable=False),
        sa.Column('error_count', sa.Integer(), default=0),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['domain_id'], ['domains.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('day', 'domain_id', 'status_code', 'path', name='uq_error_stats')
    )
    op.create_index('ix_analytics_error_stats_id', 'analytics_error_stats', ['id'])
    op.create_index('ix_analytics_error_stats_day', 'analytics_error_stats', ['day'])
    op.create_index('ix_analytics_error_stats_domain_id', 'analytics_error_stats', ['domain_id'])
    op.create_index('ix_analytics_error_stats_status_code', 'analytics_error_stats', ['status_code'])
    op.create_index('ix_error_stats_day_domain', 'analytics_error_stats', ['day', 'domain_id'])


def downgrade() -> None:
    # Drop analytics_error_stats table
    op.drop_index('ix_error_stats_day_domain', table_name='analytics_error_stats')
    op.drop_index('ix_analytics_error_stats_status_code', table_name='analytics_error_stats')
    op.drop_index('ix_analytics_error_stats_domain_id', table_name='analytics_error_stats')
    op.drop_index('ix_analytics_error_stats_day', table_name='analytics_error_stats')
    op.drop_index('ix_analytics_error_stats_id', table_name='analytics_error_stats')
    op.drop_table('analytics_error_stats')

    # Drop analytics_top_paths table
    op.drop_index('ix_top_paths_day_domain', table_name='analytics_top_paths')
    op.drop_index('ix_analytics_top_paths_domain_id', table_name='analytics_top_paths')
    op.drop_index('ix_analytics_top_paths_day', table_name='analytics_top_paths')
    op.drop_index('ix_analytics_top_paths_id', table_name='analytics_top_paths')
    op.drop_table('analytics_top_paths')

    # Drop analytics_geo_stats table
    op.drop_index('ix_geo_stats_day_domain_country', table_name='analytics_geo_stats')
    op.drop_index('ix_analytics_geo_stats_country_code', table_name='analytics_geo_stats')
    op.drop_index('ix_analytics_geo_stats_domain_id', table_name='analytics_geo_stats')
    op.drop_index('ix_analytics_geo_stats_day', table_name='analytics_geo_stats')
    op.drop_index('ix_analytics_geo_stats_id', table_name='analytics_geo_stats')
    op.drop_table('analytics_geo_stats')

    # Drop analytics_daily_stats table
    op.drop_index('ix_daily_stats_day_domain', table_name='analytics_daily_stats')
    op.drop_index('ix_analytics_daily_stats_domain_id', table_name='analytics_daily_stats')
    op.drop_index('ix_analytics_daily_stats_day', table_name='analytics_daily_stats')
    op.drop_index('ix_analytics_daily_stats_id', table_name='analytics_daily_stats')
    op.drop_table('analytics_daily_stats')

    # Drop analytics_hourly_stats table
    op.drop_index('ix_hourly_stats_hour_domain', table_name='analytics_hourly_stats')
    op.drop_index('ix_analytics_hourly_stats_edge_node_id', table_name='analytics_hourly_stats')
    op.drop_index('ix_analytics_hourly_stats_domain_id', table_name='analytics_hourly_stats')
    op.drop_index('ix_analytics_hourly_stats_hour', table_name='analytics_hourly_stats')
    op.drop_index('ix_analytics_hourly_stats_id', table_name='analytics_hourly_stats')
    op.drop_table('analytics_hourly_stats')
