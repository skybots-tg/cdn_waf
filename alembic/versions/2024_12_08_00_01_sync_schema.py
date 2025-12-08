"""Sync schema: edge_nodes fields, rate_limits columns, certificates fields.

This migration is idempotent across nodes (central, DNS, edge) and
adds missing columns that exist in the models but may be absent in
older databases. Where possible it backfills data from legacy columns.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "2024_12_08_00_01_sync_schema"
down_revision = "2024_12_07_00_00_add_cert_columns"
branch_labels = None
depends_on = None


def _has_column(inspector, table, column):
    return column in [c["name"] for c in inspector.get_columns(table)]


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    # --- edge_nodes ---
    edge_cols = {
        "ipv6_address": sa.Column("ipv6_address", sa.String(45)),
        "location_code": sa.Column("location_code", sa.String(20), nullable=False, server_default="RU"),
        "country_code": sa.Column("country_code", sa.String(2), server_default="RU"),
        "city": sa.Column("city", sa.String(100)),
        "datacenter": sa.Column("datacenter", sa.String(255)),
        "ssh_host": sa.Column("ssh_host", sa.String(255)),
        "ssh_port": sa.Column("ssh_port", sa.Integer, server_default="22"),
        "ssh_user": sa.Column("ssh_user", sa.String(255)),
        "ssh_key": sa.Column("ssh_key", sa.Text),
        "ssh_password": sa.Column("ssh_password", sa.String(255)),
        "api_key": sa.Column("api_key", sa.String(64)),
        "last_heartbeat": sa.Column("last_heartbeat", sa.DateTime),
        "cpu_usage": sa.Column("cpu_usage", sa.Float),
        "memory_usage": sa.Column("memory_usage", sa.Float),
        "disk_usage": sa.Column("disk_usage", sa.Float),
        "config_version": sa.Column("config_version", sa.Integer, nullable=False, server_default="0"),
        "last_config_update": sa.Column("last_config_update", sa.DateTime),
        "created_at": sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
        "updated_at": sa.Column("updated_at", sa.DateTime, server_default=sa.text("NOW()")),
    }
    for name, column in edge_cols.items():
        if not _has_column(inspector, "edge_nodes", name):
            op.add_column("edge_nodes", column)

    # --- rate_limits ---
    rl_cols = {
        "limit_value": sa.Column("limit_value", sa.Integer, nullable=False, server_default="10"),
        "interval_seconds": sa.Column("interval_seconds", sa.Integer, nullable=False, server_default="60"),
        "action": sa.Column("action", sa.String(20), nullable=False, server_default="block"),
        "block_duration": sa.Column("block_duration", sa.Integer, nullable=False, server_default="300"),
        "response_status": sa.Column("response_status", sa.Integer, nullable=False, server_default="429"),
        "response_body": sa.Column("response_body", sa.Text),
        "enabled": sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        "created_at": sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
        "updated_at": sa.Column("updated_at", sa.DateTime, server_default=sa.text("NOW()")),
    }
    for name, column in rl_cols.items():
        if not _has_column(inspector, "rate_limits", name):
            op.add_column("rate_limits", column)

    # backfill from legacy columns if present
    if _has_column(inspector, "rate_limits", "limit"):
        op.execute(
            "UPDATE rate_limits SET limit_value = limit WHERE limit_value IS NULL"
        )
    if _has_column(inspector, "rate_limits", "interval"):
        op.execute(
            "UPDATE rate_limits SET interval_seconds = interval WHERE interval_seconds IS NULL"
        )

    # --- certificates ---
    cert_cols = {
        "issuer": sa.Column("issuer", sa.String(500)),
        "subject": sa.Column("subject", sa.String(500)),
        "san": sa.Column("san", sa.Text),
        "not_before": sa.Column("not_before", sa.DateTime),
        "not_after": sa.Column("not_after", sa.DateTime),
        "cert_pem": sa.Column("cert_pem", sa.Text),
        "key_pem": sa.Column("key_pem", sa.Text),
        "chain_pem": sa.Column("chain_pem", sa.Text),
        "acme_order_url": sa.Column("acme_order_url", sa.String(512)),
        "acme_account_key": sa.Column("acme_account_key", sa.Text),
        "acme_challenge_type": sa.Column("acme_challenge_type", sa.String(20)),
        "auto_renew": sa.Column("auto_renew", sa.Boolean, nullable=False, server_default=sa.text("true")),
        "renew_before_days": sa.Column("renew_before_days", sa.Integer, nullable=False, server_default="30"),
        "last_renewed_at": sa.Column("last_renewed_at", sa.DateTime),
        "created_at": sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
        "updated_at": sa.Column("updated_at", sa.DateTime, server_default=sa.text("NOW()")),
    }
    for name, column in cert_cols.items():
        if not _has_column(inspector, "certificates", name):
            op.add_column("certificates", column)


def downgrade():
    # Non-destructive: do nothing on downgrade to avoid data loss.
    pass

