"""Complete initial schema for CDN/WAF platform.

Revision ID: 0001
Revises: -
Create Date: 2026-03-25
"""
from alembic import op
import sqlalchemy as sa

from app.models.organization import OrganizationRole
from app.models.domain import DomainStatus, TLSMode
from app.models.cache import CacheRuleType
from app.models.waf import WAFAction
from app.models.certificate import CertificateType, CertificateStatus
from app.models.certificate_log import CertificateLogLevel

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _create_enums(bind):
    for enum_type in (
        sa.Enum(OrganizationRole, name="organizationrole"),
        sa.Enum(DomainStatus, name="domainstatus"),
        sa.Enum(TLSMode, name="tlsmode"),
        sa.Enum(CacheRuleType, name="cacheruletype"),
        sa.Enum(WAFAction, name="wafaction"),
        sa.Enum(CertificateType, name="certificatetype"),
        sa.Enum(CertificateStatus, name="certificatestatus"),
        sa.Enum(CertificateLogLevel, name="certificateloglevel"),
    ):
        enum_type.create(bind, checkfirst=True)


def upgrade() -> None:
    bind = op.get_bind()
    _create_enums(bind)

    organization_role = sa.Enum(OrganizationRole, name="organizationrole", create_type=False)
    domain_status = sa.Enum(DomainStatus, name="domainstatus", create_type=False)
    tls_mode = sa.Enum(TLSMode, name="tlsmode", create_type=False)
    cache_rule_type = sa.Enum(CacheRuleType, name="cacheruletype", create_type=False)
    waf_action = sa.Enum(WAFAction, name="wafaction", create_type=False)
    certificate_type = sa.Enum(CertificateType, name="certificatetype", create_type=False)
    certificate_status = sa.Enum(CertificateStatus, name="certificatestatus", create_type=False)
    certificate_log_level = sa.Enum(CertificateLogLevel, name="certificateloglevel", create_type=False)

    # ── users ──
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("totp_secret", sa.String(32)),
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime()),
        sa.Column("last_login", sa.DateTime()),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ── api_tokens ──
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("scopes", sa.Text()),
        sa.Column("allowed_ips", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("expires_at", sa.DateTime()),
        sa.Column("last_used_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("token_hash", name="uq_api_tokens_token_hash"),
    )
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"])

    # ── organizations ──
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_organizations_owner_id", "organizations", ["owner_id"])

    # ── organization_members ──
    op.create_table(
        "organization_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", organization_role, nullable=False, server_default=OrganizationRole.MEMBER.value),
        sa.Column("invited_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("joined_at", sa.DateTime()),
    )
    op.create_index("ix_org_members_org_id", "organization_members", ["organization_id"])
    op.create_index("ix_org_members_user_id", "organization_members", ["user_id"])

    # ── domains ──
    op.create_table(
        "domains",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", domain_status, nullable=False, server_default=DomainStatus.PENDING.value),
        sa.Column("verification_token", sa.String(64)),
        sa.Column("ns_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ns_verified_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime()),
        sa.UniqueConstraint("name", name="uq_domains_name"),
    )
    op.create_index("ix_domains_org_id", "domains", ["organization_id"])
    op.create_index("ix_domains_name", "domains", ["name"], unique=True)

    # ── api_token_domains (M2M) ──
    op.create_table(
        "api_token_domains",
        sa.Column("api_token_id", sa.Integer(), sa.ForeignKey("api_tokens.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id", ondelete="CASCADE"), primary_key=True),
    )

    # ── domain_tls_settings ──
    op.create_table(
        "domain_tls_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id"), nullable=False, unique=True),
        sa.Column("mode", tls_mode, nullable=False, server_default=TLSMode.FLEXIBLE.value),
        sa.Column("force_https", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("hsts_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("hsts_max_age", sa.Integer(), nullable=False, server_default="31536000"),
        sa.Column("hsts_include_subdomains", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("hsts_preload", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("min_tls_version", sa.String(10), nullable=False, server_default="1.2"),
        sa.Column("auto_certificate", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_domain_tls_settings_domain_id", "domain_tls_settings", ["domain_id"])

    # ── dns_records ──
    op.create_table(
        "dns_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id"), nullable=False),
        sa.Column("type", sa.String(10), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("ttl", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column("priority", sa.Integer()),
        sa.Column("weight", sa.Integer()),
        sa.Column("proxied", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("comment", sa.String(255)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_dns_records_domain_id", "dns_records", ["domain_id"])
    op.create_index("ix_dns_records_name", "dns_records", ["name"])

    # ── origins ──
    op.create_table(
        "origins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("origin_host", sa.String(255), nullable=False),
        sa.Column("origin_port", sa.Integer(), nullable=False, server_default="443"),
        sa.Column("protocol", sa.String(10), nullable=False, server_default="https"),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("is_backup", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("health_check_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("health_check_url", sa.String(255), nullable=False, server_default="/"),
        sa.Column("health_check_interval", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("health_check_timeout", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("health_check_unhealthy_threshold", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("health_check_healthy_threshold", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("health_status", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("is_healthy", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_health_check", sa.DateTime()),
        sa.Column("last_check_at", sa.DateTime()),
        sa.Column("last_health_check_response_time", sa.Float()),
        sa.Column("last_check_duration", sa.Float()),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_origins_domain_id", "origins", ["domain_id"])

    # ── cache_rules ──
    op.create_table(
        "cache_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id"), nullable=False),
        sa.Column("pattern", sa.String(255), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rule_type", cache_rule_type, nullable=False, server_default=CacheRuleType.CACHE.value),
        sa.Column("ttl", sa.Integer()),
        sa.Column("respect_origin_headers", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("bypass_cookies", sa.Text()),
        sa.Column("bypass_query_params", sa.Text()),
        sa.Column("cache_by_query_string", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("cache_by_device_type", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_cache_rules_domain_id", "cache_rules", ["domain_id"])

    # ── cache_purges ──
    op.create_table(
        "cache_purges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id"), nullable=False),
        sa.Column("purge_type", sa.String(20), nullable=False),
        sa.Column("targets", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("initiated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime()),
    )
    op.create_index("ix_cache_purges_domain_id", "cache_purges", ["domain_id"])
    op.create_index("ix_cache_purges_initiated_by", "cache_purges", ["initiated_by"])

    # ── waf_rules ──
    op.create_table(
        "waf_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("action", waf_action, nullable=False, server_default=WAFAction.BLOCK.value),
        sa.Column("conditions", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_waf_rules_domain_id", "waf_rules", ["domain_id"])

    # ── rate_limits ──
    op.create_table(
        "rate_limits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("key_type", sa.String(50), nullable=False, server_default="ip"),
        sa.Column("custom_key", sa.String(255)),
        sa.Column("path_pattern", sa.String(255)),
        sa.Column("limit_value", sa.Integer(), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False, server_default="block"),
        sa.Column("block_duration", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("response_status", sa.Integer(), nullable=False, server_default="429"),
        sa.Column("response_body", sa.Text()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_rate_limits_domain_id", "rate_limits", ["domain_id"])

    # ── ip_access_rules ──
    op.create_table(
        "ip_access_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id"), nullable=False),
        sa.Column("rule_type", sa.String(20), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_ip_access_rules_domain_id", "ip_access_rules", ["domain_id"])

    # ── certificates ──
    op.create_table(
        "certificates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id"), nullable=False),
        sa.Column("type", certificate_type, nullable=False, server_default=CertificateType.ACME.value),
        sa.Column("status", certificate_status, nullable=False, server_default=CertificateStatus.PENDING.value),
        sa.Column("common_name", sa.String(255), nullable=False),
        sa.Column("san", sa.Text()),
        sa.Column("issuer", sa.String(500)),
        sa.Column("subject", sa.String(500)),
        sa.Column("not_before", sa.DateTime()),
        sa.Column("not_after", sa.DateTime()),
        sa.Column("cert_pem", sa.Text()),
        sa.Column("key_pem", sa.Text()),
        sa.Column("chain_pem", sa.Text()),
        sa.Column("acme_order_url", sa.String(512)),
        sa.Column("acme_account_key", sa.Text()),
        sa.Column("acme_challenge_type", sa.String(20)),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("renew_before_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("last_renewed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_certificates_domain_id", "certificates", ["domain_id"])

    # ── certificate_logs ──
    op.create_table(
        "certificate_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("certificate_id", sa.Integer(), sa.ForeignKey("certificates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("level", certificate_log_level, nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_certificate_logs_certificate_id", "certificate_logs", ["certificate_id"])

    # ── edge_nodes ──
    op.create_table(
        "edge_nodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=False),
        sa.Column("ipv6_address", sa.String(45)),
        sa.Column("location_code", sa.String(20), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False, server_default="RU"),
        sa.Column("city", sa.String(100)),
        sa.Column("datacenter", sa.String(255)),
        sa.Column("ssh_host", sa.String(255)),
        sa.Column("ssh_port", sa.Integer(), server_default="22"),
        sa.Column("ssh_user", sa.String(255)),
        sa.Column("ssh_key", sa.Text()),
        sa.Column("ssh_password", sa.String(255)),
        sa.Column("api_key", sa.String(64)),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("status", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("last_heartbeat", sa.DateTime()),
        sa.Column("cpu_usage", sa.Float()),
        sa.Column("memory_usage", sa.Float()),
        sa.Column("disk_usage", sa.Float()),
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_config_update", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime()),
        sa.UniqueConstraint("name", name="uq_edge_nodes_name"),
        sa.UniqueConstraint("api_key", name="uq_edge_nodes_api_key"),
    )
    op.create_index("ix_edge_nodes_name", "edge_nodes", ["name"], unique=True)

    # ── dns_nodes ──
    op.create_table(
        "dns_nodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("hostname", sa.String(255), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=False),
        sa.Column("ipv6_address", sa.String(45)),
        sa.Column("location_code", sa.String(20), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False, server_default="RU"),
        sa.Column("city", sa.String(100)),
        sa.Column("datacenter", sa.String(255)),
        sa.Column("ssh_host", sa.String(255)),
        sa.Column("ssh_port", sa.Integer(), server_default="22"),
        sa.Column("ssh_user", sa.String(255)),
        sa.Column("ssh_key", sa.Text()),
        sa.Column("ssh_password", sa.String(255)),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("status", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("last_heartbeat", sa.DateTime()),
        sa.Column("cpu_usage", sa.Float()),
        sa.Column("memory_usage", sa.Float()),
        sa.Column("disk_usage", sa.Float()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime()),
        sa.UniqueConstraint("name", name="uq_dns_nodes_name"),
        sa.UniqueConstraint("hostname", name="uq_dns_nodes_hostname"),
    )
    op.create_index("ix_dns_nodes_name", "dns_nodes", ["name"], unique=True)
    op.create_index("ix_dns_nodes_hostname", "dns_nodes", ["hostname"], unique=True)

    # ── request_logs ──
    op.create_table(
        "request_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id")),
        sa.Column("edge_node_id", sa.Integer(), sa.ForeignKey("edge_nodes.id", ondelete="SET NULL")),
        sa.Column("method", sa.String(10)),
        sa.Column("path", sa.String(2048)),
        sa.Column("query_string", sa.String(2048)),
        sa.Column("status_code", sa.Integer()),
        sa.Column("bytes_sent", sa.BigInteger()),
        sa.Column("client_ip", sa.String(45)),
        sa.Column("user_agent", sa.String(512)),
        sa.Column("referer", sa.String(2048)),
        sa.Column("request_time", sa.Integer()),
        sa.Column("cache_status", sa.String(20)),
        sa.Column("waf_status", sa.String(20)),
        sa.Column("waf_rule_id", sa.Integer()),
        sa.Column("country_code", sa.String(2)),
    )
    op.create_index("ix_request_logs_domain_id", "request_logs", ["domain_id"])
    op.create_index("ix_request_logs_edge_node_id", "request_logs", ["edge_node_id"])
    op.create_index("ix_request_logs_timestamp", "request_logs", ["timestamp"])

    # ── analytics_hourly_stats ──
    op.create_table(
        "analytics_hourly_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("hour", sa.DateTime(), nullable=False),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id", ondelete="CASCADE")),
        sa.Column("edge_node_id", sa.Integer(), sa.ForeignKey("edge_nodes.id", ondelete="SET NULL")),
        sa.Column("total_requests", sa.BigInteger(), server_default="0"),
        sa.Column("total_bytes_sent", sa.BigInteger(), server_default="0"),
        sa.Column("total_bytes_received", sa.BigInteger(), server_default="0"),
        sa.Column("status_2xx", sa.Integer(), server_default="0"),
        sa.Column("status_3xx", sa.Integer(), server_default="0"),
        sa.Column("status_4xx", sa.Integer(), server_default="0"),
        sa.Column("status_5xx", sa.Integer(), server_default="0"),
        sa.Column("cache_hits", sa.Integer(), server_default="0"),
        sa.Column("cache_misses", sa.Integer(), server_default="0"),
        sa.Column("cache_bypass", sa.Integer(), server_default="0"),
        sa.Column("waf_blocked", sa.Integer(), server_default="0"),
        sa.Column("waf_challenged", sa.Integer(), server_default="0"),
        sa.Column("avg_response_time", sa.Float(), server_default="0"),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.UniqueConstraint("hour", "domain_id", "edge_node_id", name="uq_hourly_stats"),
    )
    op.create_index("ix_analytics_hourly_stats_hour", "analytics_hourly_stats", ["hour"])
    op.create_index("ix_analytics_hourly_stats_domain_id", "analytics_hourly_stats", ["domain_id"])
    op.create_index("ix_analytics_hourly_stats_edge_node_id", "analytics_hourly_stats", ["edge_node_id"])
    op.create_index("ix_hourly_stats_hour_domain", "analytics_hourly_stats", ["hour", "domain_id"])

    # ── analytics_daily_stats ──
    op.create_table(
        "analytics_daily_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id", ondelete="CASCADE")),
        sa.Column("total_requests", sa.BigInteger(), server_default="0"),
        sa.Column("total_bytes_sent", sa.BigInteger(), server_default="0"),
        sa.Column("total_bytes_received", sa.BigInteger(), server_default="0"),
        sa.Column("status_2xx", sa.Integer(), server_default="0"),
        sa.Column("status_3xx", sa.Integer(), server_default="0"),
        sa.Column("status_4xx", sa.Integer(), server_default="0"),
        sa.Column("status_5xx", sa.Integer(), server_default="0"),
        sa.Column("cache_hits", sa.Integer(), server_default="0"),
        sa.Column("cache_misses", sa.Integer(), server_default="0"),
        sa.Column("cache_bypass", sa.Integer(), server_default="0"),
        sa.Column("waf_blocked", sa.Integer(), server_default="0"),
        sa.Column("waf_challenged", sa.Integer(), server_default="0"),
        sa.Column("avg_response_time", sa.Float(), server_default="0"),
        sa.Column("peak_requests_hour", sa.Integer(), server_default="0"),
        sa.Column("peak_bandwidth_hour", sa.BigInteger(), server_default="0"),
        sa.Column("unique_visitors", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.UniqueConstraint("day", "domain_id", name="uq_daily_stats"),
    )
    op.create_index("ix_analytics_daily_stats_day", "analytics_daily_stats", ["day"])
    op.create_index("ix_analytics_daily_stats_domain_id", "analytics_daily_stats", ["domain_id"])
    op.create_index("ix_daily_stats_day_domain", "analytics_daily_stats", ["day", "domain_id"])

    # ── analytics_geo_stats ──
    op.create_table(
        "analytics_geo_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id", ondelete="CASCADE")),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("total_requests", sa.BigInteger(), server_default="0"),
        sa.Column("total_bytes_sent", sa.BigInteger(), server_default="0"),
        sa.Column("unique_visitors", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime()),
        sa.UniqueConstraint("day", "domain_id", "country_code", name="uq_geo_stats"),
    )
    op.create_index("ix_analytics_geo_stats_day", "analytics_geo_stats", ["day"])
    op.create_index("ix_analytics_geo_stats_domain_id", "analytics_geo_stats", ["domain_id"])
    op.create_index("ix_analytics_geo_stats_country_code", "analytics_geo_stats", ["country_code"])
    op.create_index("ix_geo_stats_day_domain_country", "analytics_geo_stats", ["day", "domain_id", "country_code"])

    # ── analytics_top_paths ──
    op.create_table(
        "analytics_top_paths",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id", ondelete="CASCADE"), nullable=False),
        sa.Column("path", sa.String(2048), nullable=False),
        sa.Column("total_requests", sa.BigInteger(), server_default="0"),
        sa.Column("total_bytes_sent", sa.BigInteger(), server_default="0"),
        sa.Column("cache_hits", sa.Integer(), server_default="0"),
        sa.Column("cache_misses", sa.Integer(), server_default="0"),
        sa.Column("status_2xx", sa.Integer(), server_default="0"),
        sa.Column("status_4xx", sa.Integer(), server_default="0"),
        sa.Column("status_5xx", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime()),
        sa.UniqueConstraint("day", "domain_id", "path", name="uq_top_paths"),
    )
    op.create_index("ix_analytics_top_paths_day", "analytics_top_paths", ["day"])
    op.create_index("ix_analytics_top_paths_domain_id", "analytics_top_paths", ["domain_id"])
    op.create_index("ix_top_paths_day_domain", "analytics_top_paths", ["day", "domain_id"])

    # ── analytics_error_stats ──
    op.create_table(
        "analytics_error_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(2048), nullable=False),
        sa.Column("error_count", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime()),
        sa.UniqueConstraint("day", "domain_id", "status_code", "path", name="uq_error_stats"),
    )
    op.create_index("ix_analytics_error_stats_day", "analytics_error_stats", ["day"])
    op.create_index("ix_analytics_error_stats_domain_id", "analytics_error_stats", ["domain_id"])
    op.create_index("ix_analytics_error_stats_status_code", "analytics_error_stats", ["status_code"])
    op.create_index("ix_error_stats_day_domain", "analytics_error_stats", ["day", "domain_id"])


def downgrade() -> None:
    for table in (
        "analytics_error_stats",
        "analytics_top_paths",
        "analytics_geo_stats",
        "analytics_daily_stats",
        "analytics_hourly_stats",
        "request_logs",
        "dns_nodes",
        "edge_nodes",
        "certificate_logs",
        "certificates",
        "ip_access_rules",
        "rate_limits",
        "waf_rules",
        "cache_purges",
        "cache_rules",
        "origins",
        "dns_records",
        "domain_tls_settings",
        "api_token_domains",
        "domains",
        "organization_members",
        "organizations",
        "api_tokens",
        "users",
    ):
        op.drop_table(table)

    bind = op.get_bind()
    for name in (
        "certificateloglevel",
        "certificatestatus",
        "certificatetype",
        "wafaction",
        "cacheruletype",
        "tlsmode",
        "domainstatus",
        "organizationrole",
    ):
        sa.Enum(name=name).drop(bind, checkfirst=True)
