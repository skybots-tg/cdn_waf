"""
Правила кэша в конфиге edge-ноды — как у Cloudflare.

До 23.09.2026 шаблон знал только «кэшировать с TTL»: тип правила (bypass),
«не уважать заголовки origin», обход по cookie панель хранила, но нода их
не применяла. Кэш зоны жил 10 минут без запросов, статуса кэша в ответе не
было, а падение origin сразу превращалось в ошибку у посетителя.
"""

import os
import re
import secrets
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

for _key, _value in {
    "SECRET_KEY": "test-secret",
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db",
    "REDIS_URL": "redis://localhost:6379/0",
    "CELERY_BROKER_URL": "redis://localhost:6379/1",
    "CELERY_RESULT_BACKEND": "redis://localhost:6379/2",
    "JWT_SECRET_KEY": secrets.token_hex(32),
    "ACME_EMAIL": "test@example.com",
}.items():
    os.environ.setdefault(_key, _value)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "edge_node"))
for _name in ("aiofiles", "psutil"):
    try:
        __import__(_name)
    except ImportError:
        _stub = types.ModuleType(_name)
        _stub.__getattr__ = lambda attr: MagicMock()  # noqa: B023
        sys.modules[_name] = _stub

import edge_config_updater as agent  # noqa: E402
from app.api.internal import _cookie_names  # noqa: E402


def _render(rules, **extra):
    domain = {
        "name": "example.com",
        "tls_settings": {"mode": "flexible"},
        "tls": {"enabled": False},
        "origins": [{"host": "198.51.100.1", "port": 80, "protocol": "http", "weight": 100}],
        "cache_rules": rules,
        **extra,
    }
    return agent.NGINX_TEMPLATE.render(
        domains=[domain], global_settings={"control_plane_url": "https://panel.test"},
    )


def _location(conf, pattern):
    """Тело первого location ~ pattern."""
    start = conf.index("location ~ " + pattern)
    return conf[start:conf.index("proxy_pass", start)]


def test_cache_rule_like_cloudflare():
    conf = _render([{
        "pattern": r"\.(css|js)$", "rule_type": "cache", "ttl": 3600,
        "respect_origin": False, "bypass_cookie_names": ["session"],
    }])
    block = _location(conf, r"\.(css|js)$")
    assert "proxy_cache example_com;" in block
    assert "proxy_cache_valid 200 206 301 302 3600s;" in block
    assert "proxy_ignore_headers Cache-Control Expires;" in block
    assert "proxy_cache_bypass $cookie_session;" in block
    assert "proxy_cache_use_stale error timeout updating" in block
    assert "proxy_cache_lock on;" in block
    assert "add_header X-Cache-Status $upstream_cache_status always;" in block


def test_respecting_origin_does_not_ignore_its_headers():
    block = _location(_render([{"pattern": "^/static/", "rule_type": "cache", "ttl": 600,
                                "respect_origin": True}]), "^/static/")
    assert "proxy_ignore_headers" not in block


def test_bypass_rule_does_not_cache():
    block = _location(_render([{"pattern": "^/api/", "rule_type": "bypass", "ttl": None}]), "^/api/")
    assert "proxy_cache " not in block
    assert "X-Cache-Status BYPASS" in block


def test_dev_mode_turns_cache_rules_into_bypass():
    """Development Mode: копии из кэша не отдаются, пока режим включён."""
    rule = {"pattern": "^/static/", "rule_type": "cache", "ttl": 600, "respect_origin": True}
    block = _location(_render([rule], dev_mode=True), "^/static/")
    assert "proxy_cache " not in block
    assert "X-Cache-Status BYPASS" in block
    assert "proxy_cache example_com;" in _location(_render([rule], dev_mode=False), "^/static/")


def test_cache_zone_lives_a_week_with_size_limit():
    conf = _render([])
    zone = re.search(r"proxy_cache_path /var/cache/nginx/example_com [^;]+;", conf).group(0)
    assert "inactive=7d" in zone and "max_size=256m" in zone


def test_log_format_has_origin_timing():
    for field in ("upstream_time", "upstream_status", "request_length"):
        assert f'"{field}"' in agent.LOG_FORMAT_CONF


def test_cookie_names_are_sanitized():
    assert _cookie_names('["session", "wp_logged_in", "bad-name", "x;y", 5]') == ["session", "wp_logged_in"]
    assert _cookie_names(None) == []
    assert _cookie_names("не json") == []
