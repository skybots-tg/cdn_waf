"""Initial schema: creates all core tables for CDN/WAF platform."""
from alembic import op
import sqlalchemy as sa

from app.models.organization import OrganizationRole
from app.models.domain import DomainStatus, TLSMode
from app.models.cache import CacheRuleType
from app.models.waf import WAFAction
from app.models.certificate import CertificateType, CertificateStatus

# revision identifiers, used by Alembic.
revision = "9188ee2f20e6"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    organization_role = sa.Enum(OrganizationRole, name="organizationrole")
    domain_status = sa.Enum(DomainStatus, name="domainstatus")
    tls_mode = sa.Enum(TLSMode, name="tlsmode")
    cache_rule_type = sa.Enum(CacheRuleType, name="cacheruletype")
    waf_action = sa.Enum(WAFAction, name="wafaction")
    certificate_type = sa.Enum(CertificateType, name="certificatetype")
    certificate_status = sa.Enum(CertificateStatus, name="certificatestatus")

    bind = op.get_bind()
    for enum_type in (
        organization_role,
        domain_status,
        tls_mode,
        cache_rule_type,
        waf_action,
        certificate_type,
        certificate_status,
    ):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("totp_secret", sa.String(length=32)),
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime()),
        sa.Column("last_login", sa.DateTime()),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("scopes", sa.Text()),
        sa.Column("allowed_ips", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("expires_at", sa.DateTime()),
        sa.Column("last_used_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("token_hash", name="uq_api_tokens_token_hash"),
    )
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"])

    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_organizations_owner_id", "organizations", ["owner_id"])

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

    op.create_table(
        "domains",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", domain_status, nullable=False, server_default=DomainStatus.PENDING.value),
        sa.Column("verification_token", sa.String(length=64)),
        sa.Column("ns_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ns_verified_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime()),
        sa.UniqueConstraint("name", name="uq_domains_name"),
    )
    op.create_index("ix_domains_org_id", "domains", ["organization_id"])
    op.create_index("ix_domains_name", "domains", ["name"], unique=True)

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
        sa.Column("min_tls_version", sa.String(length=10), nullable=False, server_default="1.2"),
        sa.Column("auto_certificate", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_domain_tls_settings_domain_id", "domain_tls_settings", ["domain_id"])

    op.create_table(
        "dns_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id"), nullable=False),
        sa.Column("type", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("ttl", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column("priority", sa.Integer()),
        sa.Column("weight", sa.Integer()),
        sa.Column("proxied", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("comment", sa.String(length=255)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_dns_records_domain_id", "dns_records", ["domain_id"])
    op.create_index("ix_dns_records_name", "dns_records", ["name"])

    op.create_table(
        "origins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("origin_host", sa.String(length=255), nullable=False),
        sa.Column("origin_port", sa.Integer(), nullable=False, server_default="443"),
        sa.Column("protocol", sa.String(length=10), nullable=False, server_default="https"),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("is_backup", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("health_check_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("health_check_url", sa.String(length=255), nullable=False, server_default="/"),
        sa.Column("health_check_interval", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("health_check_timeout", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("health_check_unhealthy_threshold", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("health_check_healthy_threshold", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("health_status", sa.String(length=20), nullable=False, server_default="unknown"),
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

    op.create_table(
        "cache_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id"), nullable=False),
        sa.Column("pattern", sa.String(length=255), nullable=False),
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

    op.create_table(
        "cache_purges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id"), nullable=False),
        sa.Column("purge_type", sa.String(length=20), nullable=False),
        sa.Column("targets", sa.Text()),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("initiated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime()),
    )
    op.create_index("ix_cache_purges_domain_id", "cache_purges", ["domain_id"])
    op.create_index("ix_cache_purges_initiated_by", "cache_purges", ["initiated_by"])

    op.create_table(
        "waf_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("action", waf_action, nullable=False, server_default=WAFAction.BLOCK.value),
        sa.Column("conditions", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_waf_rules_domain_id", "waf_rules", ["domain_id"])

    op.create_table(
        "rate_limits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("key_type", sa.String(length=50), nullable=False, server_default="ip"),
        sa.Column("custom_key", sa.String(length=255)),
        sa.Column("path_pattern", sa.String(length=255)),
        sa.Column("limit_value", sa.Integer(), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False, server_default="block"),
        sa.Column("block_duration", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("response_status", sa.Integer(), nullable=False, server_default="429"),
        sa.Column("response_body", sa.Text()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_rate_limits_domain_id", "rate_limits", ["domain_id"])

    op.create_table(
        "ip_access_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id"), nullable=False),
        sa.Column("rule_type", sa.String(length=20), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_ip_access_rules_domain_id", "ip_access_rules", ["domain_id"])

    op.create_table(
        "certificates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id"), nullable=False),
        sa.Column("type", certificate_type, nullable=False, server_default=CertificateType.ACME.value),
        sa.Column("status", certificate_status, nullable=False, server_default=CertificateStatus.PENDING.value),
        sa.Column("common_name", sa.String(length=255), nullable=False),
        sa.Column("san", sa.Text()),
        sa.Column("issuer", sa.String(length=500)),
        sa.Column("subject", sa.String(length=500)),
        sa.Column("not_before", sa.DateTime()),
        sa.Column("not_after", sa.DateTime()),
        sa.Column("cert_pem", sa.Text()),
        sa.Column("key_pem", sa.Text()),
        sa.Column("chain_pem", sa.Text()),
        sa.Column("acme_order_url", sa.String(length=512)),
        sa.Column("acme_account_key", sa.Text()),
        sa.Column("acme_challenge_type", sa.String(length=20)),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("renew_before_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("last_renewed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_certificates_domain_id", "certificates", ["domain_id"])

    op.create_table(
        "edge_nodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=False),
        sa.Column("ipv6_address", sa.String(length=45)),
        sa.Column("location_code", sa.String(length=20), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False, server_default="RU"),
        sa.Column("city", sa.String(length=100)),
        sa.Column("datacenter", sa.String(length=255)),
        sa.Column("ssh_host", sa.String(length=255)),
        sa.Column("ssh_port", sa.Integer(), server_default="22"),
        sa.Column("ssh_user", sa.String(length=255)),
        sa.Column("ssh_key", sa.Text()),
        sa.Column("ssh_password", sa.String(length=255)),
        sa.Column("api_key", sa.String(length=64)),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="unknown"),
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

    op.create_table(
        "dns_nodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=False),
        sa.Column("ipv6_address", sa.String(length=45)),
        sa.Column("location_code", sa.String(length=20), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False, server_default="RU"),
        sa.Column("city", sa.String(length=100)),
        sa.Column("datacenter", sa.String(length=255)),
        sa.Column("ssh_host", sa.String(length=255)),
        sa.Column("ssh_port", sa.Integer(), server_default="22"),
        sa.Column("ssh_user", sa.String(length=255)),
        sa.Column("ssh_key", sa.Text()),
        sa.Column("ssh_password", sa.String(length=255)),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="unknown"),
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

    op.create_table(
        "request_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("domain_id", sa.Integer(), sa.ForeignKey("domains.id")),
        sa.Column("edge_node_id", sa.Integer(), sa.ForeignKey("edge_nodes.id")),
        sa.Column("method", sa.String(length=10)),
        sa.Column("path", sa.String(length=2048)),
        sa.Column("query_string", sa.String(length=2048)),
        sa.Column("status_code", sa.Integer()),
        sa.Column("bytes_sent", sa.BigInteger()),
        sa.Column("client_ip", sa.String(length=45)),
        sa.Column("user_agent", sa.String(length=512)),
        sa.Column("referer", sa.String(length=2048)),
        sa.Column("request_time", sa.Integer()),
        sa.Column("cache_status", sa.String(length=20)),
        sa.Column("waf_status", sa.String(length=20)),
        sa.Column("waf_rule_id", sa.Integer()),
        sa.Column("country_code", sa.String(length=2)),
    )
    op.create_index("ix_request_logs_domain_id", "request_logs", ["domain_id"])
    op.create_index("ix_request_logs_edge_node_id", "request_logs", ["edge_node_id"])
    op.create_index("ix_request_logs_timestamp", "request_logs", ["timestamp"])


def downgrade() -> None:
    op.drop_index("ix_request_logs_timestamp", table_name="request_logs")
    op.drop_index("ix_request_logs_edge_node_id", table_name="request_logs")
    op.drop_index("ix_request_logs_domain_id", table_name="request_logs")
    op.drop_table("request_logs")

    op.drop_index("ix_dns_nodes_hostname", table_name="dns_nodes")
    op.drop_index("ix_dns_nodes_name", table_name="dns_nodes")
    op.drop_table("dns_nodes")

    op.drop_index("ix_edge_nodes_name", table_name="edge_nodes")
    op.drop_table("edge_nodes")

    op.drop_index("ix_certificates_domain_id", table_name="certificates")
    op.drop_table("certificates")

    op.drop_index("ix_ip_access_rules_domain_id", table_name="ip_access_rules")
    op.drop_table("ip_access_rules")

    op.drop_index("ix_rate_limits_domain_id", table_name="rate_limits")
    op.drop_table("rate_limits")

    op.drop_index("ix_waf_rules_domain_id", table_name="waf_rules")
    op.drop_table("waf_rules")

    op.drop_index("ix_cache_purges_initiated_by", table_name="cache_purges")
    op.drop_index("ix_cache_purges_domain_id", table_name="cache_purges")
    op.drop_table("cache_purges")

    op.drop_index("ix_cache_rules_domain_id", table_name="cache_rules")
    op.drop_table("cache_rules")

    op.drop_index("ix_origins_domain_id", table_name="origins")
    op.drop_table("origins")

    op.drop_index("ix_dns_records_name", table_name="dns_records")
    op.drop_index("ix_dns_records_domain_id", table_name="dns_records")
    op.drop_table("dns_records")

    op.drop_index("ix_domain_tls_settings_domain_id", table_name="domain_tls_settings")
    op.drop_table("domain_tls_settings")

    op.drop_index("ix_domains_name", table_name="domains")
    op.drop_index("ix_domains_org_id", table_name="domains")
    op.drop_table("domains")

    op.drop_index("ix_org_members_user_id", table_name="organization_members")
    op.drop_index("ix_org_members_org_id", table_name="organization_members")
    op.drop_table("organization_members")

    op.drop_index("ix_organizations_owner_id", table_name="organizations")
    op.drop_table("organizations")

    op.drop_index("ix_api_tokens_user_id", table_name="api_tokens")
    op.drop_table("api_tokens")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    organization_role = sa.Enum(OrganizationRole, name="organizationrole")
    domain_status = sa.Enum(DomainStatus, name="domainstatus")
    tls_mode = sa.Enum(TLSMode, name="tlsmode")
    cache_rule_type = sa.Enum(CacheRuleType, name="cacheruletype")
    waf_action = sa.Enum(WAFAction, name="wafaction")
    certificate_type = sa.Enum(CertificateType, name="certificatetype")
    certificate_status = sa.Enum(CertificateStatus, name="certificatestatus")

    bind = op.get_bind()
    for enum_type in (
        certificate_status,
        certificate_type,
        waf_action,
        cache_rule_type,
        tls_mode,
        domain_status,
        organization_role,
    ):
        enum_type.drop(bind, checkfirst=True)

