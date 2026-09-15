"""Shared input validators.

These exist primarily to keep tenant-supplied strings from breaking out of the
generated nginx config on edge nodes (directive injection) or from escaping a
cache/cert path on disk. They run at the API boundary; the edge agent also
re-validates as defence in depth.
"""
import ipaddress
import re

# Characters that can terminate/rewrite an nginx directive or a shell/path
# context. None of them appear in a legitimate hostname, URL pattern or path.
_NGINX_UNSAFE = set('{};#$`\\<>"\'\n\r\t')

# Hostname: dotted labels of letters/digits/hyphen, optional leading '_' (for
# DNS names like _dmarc), optional trailing dot stripped by callers.
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(_?[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?)"
    r"(\.(_?[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?))*\.?$"
)

# DNS record owner name: hostname labels plus '@' (apex) and '*' (wildcard).
_DNS_NAME_RE = re.compile(r"^(@|\*(\.[A-Za-z0-9_-]+)*|[A-Za-z0-9_*.-]{1,255})$")

MAX_DNS_CONTENT = 2048


def _reject_unsafe(value: str, field: str) -> str:
    if any(ch in _NGINX_UNSAFE for ch in value):
        raise ValueError(f"{field} contains forbidden characters")
    return value


def validate_hostname(value: str) -> str:
    v = value.strip().rstrip(".").lower()
    if not v or not _HOSTNAME_RE.match(v):
        raise ValueError("invalid hostname")
    return v


def validate_host_or_ip(value: str) -> str:
    v = value.strip()
    try:
        return str(ipaddress.ip_address(v))
    except ValueError:
        return validate_hostname(v)


def validate_url_pattern(value: str) -> str:
    """A cache/rate-limit path pattern. Reject nginx-breaking characters."""
    v = value.strip()
    if not v:
        raise ValueError("empty pattern")
    if " " in v:
        raise ValueError("pattern must not contain spaces")
    return _reject_unsafe(v, "pattern")


def validate_health_check_url(value: str) -> str:
    v = value.strip()
    if not v.startswith("/"):
        raise ValueError("health_check_url must start with '/'")
    if ".." in v or " " in v:
        raise ValueError("invalid health_check_url")
    return _reject_unsafe(v, "health_check_url")


def validate_dns_name(value: str) -> str:
    v = value.strip()
    if not _DNS_NAME_RE.match(v):
        raise ValueError("invalid DNS record name")
    return _reject_unsafe(v, "name")


def validate_dns_content(value: str) -> str:
    v = value.strip()
    if len(v) > MAX_DNS_CONTENT:
        raise ValueError("DNS record content too long")
    if "\n" in v or "\r" in v:
        raise ValueError("DNS record content must be single-line")
    return v


def validate_ip_or_cidr(value: str) -> str:
    v = value.strip()
    try:
        ipaddress.ip_network(v, strict=False)
    except ValueError:
        raise ValueError("invalid IP address or CIDR")
    return v


def sanitize_condition_values(conditions):
    """Recursively reject nginx-breaking characters in WAF condition strings."""
    def walk(node):
        if isinstance(node, str):
            _reject_unsafe(node, "condition")
        elif isinstance(node, dict):
            for val in node.values():
                walk(val)
        elif isinstance(node, (list, tuple)):
            for val in node:
                walk(val)
    walk(conditions)
    return conditions
