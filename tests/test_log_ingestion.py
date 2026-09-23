"""
Приём сырых логов от edge-нод (POST /internal/edge/logs).

Приём выключали 03.09.2026: нода повторяла партию, которую панель уже
записала, таблица росла лавиной, диск кончился, и Postgres упал вместе со
всеми проектами сервера. Здесь проверяется то, что делает повтор безвредным,
а перегруз — не смертельным:

* отпечаток строки стабилен и одинаков у повторной партии;
* зона находится по суффиксу хоста (app.example.com → example.com);
* строки чужих хостов (сканеры по IP ноды) не пишутся;
* лимит строк за час и порог свободного диска отбрасывают строки, но ответ
  остаётся успешным — иначе нода начнёт повторять.
"""

import asyncio
import os
import secrets
from collections import namedtuple

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

import pytest  # noqa: E402

from app.api import internal_logs  # noqa: E402
from app.core.config import settings  # noqa: E402

ZONES = {"example.com": 1, "perek.us": 13, "co.uk.example.org": 7}

LINE = {
    "timestamp": "2026-09-23T04:26:22+03:00",
    "domain": "App.Perek.US:443",
    "client_ip": "203.0.113.5",
    "method": "GET",
    "path": "/static/bundle/app.js?v=abc&x=1",
    "status": 200,
    "bytes_sent": 433188,
    "referer": "https://app.perek.us/",
    "user_agent": "Mozilla/5.0",
    "request_time": 0.257,
    "cache_status": "HIT",
    "country_code": "KZ",
    "waf_status": "",
    "waf_rule_id": "",
}


def test_zone_by_suffix():
    assert internal_logs._zone_for("app.perek.us", ZONES) == 13
    assert internal_logs._zone_for("perek.us", ZONES) == 13
    assert internal_logs._zone_for("a.b.example.com", ZONES) == 1


def test_zone_not_matched_for_foreign_hosts():
    for host in ("", "188.116.24.50", "evilperek.us", "example.com.evil.net", "us"):
        assert internal_logs._zone_for(host, ZONES) is None, host


def test_host_normalized():
    assert internal_logs._host_of("App.Perek.US:443") == "app.perek.us"
    assert internal_logs._host_of("perek.us.") == "perek.us"
    assert internal_logs._host_of(None) == ""


def test_fingerprint_same_for_resent_line():
    assert internal_logs._fingerprint(6, dict(LINE)) == internal_logs._fingerprint(6, dict(LINE))


def test_fingerprint_differs_by_node_and_content():
    base = internal_logs._fingerprint(6, LINE)
    assert internal_logs._fingerprint(5, LINE) != base
    assert internal_logs._fingerprint(6, dict(LINE, request_time=0.258)) != base


def test_fingerprint_fits_bigint():
    value = internal_logs._fingerprint(6, LINE)
    assert -(2 ** 63) <= value < 2 ** 63


def test_row_parsing():
    row = internal_logs._row(LINE, 6, 13, "app.perek.us")
    assert row["domain_id"] == 13 and row["host"] == "app.perek.us"
    assert row["path"] == "/static/bundle/app.js"
    assert row["query_string"] == "v=abc&x=1"
    assert row["request_time"] == 257
    assert row["timestamp"].isoformat() == "2026-09-23T01:26:22"  # UTC, без зоны
    assert row["waf_status"] is None and row["waf_rule_id"] is None
    assert row["cache_status"] == "HIT"


def test_row_survives_garbage():
    row = internal_logs._row(
        {"timestamp": "не время", "status": "-", "bytes_sent": "", "request_time": "-",
         "path": "x" * 10_000, "cache_status": "-"},
        6, 13, "perek.us",
    )
    assert row["status_code"] is None and row["bytes_sent"] == 0
    assert row["request_time"] is None and row["cache_status"] is None
    assert len(row["path"]) <= 2048


class _FakeRedis:
    def __init__(self):
        self.values = {}

    async def incrby(self, key, value):
        self.values[key] = self.values.get(key, 0) + value
        return self.values[key]

    async def expire(self, key, seconds):
        return True


DiskUsage = namedtuple("DiskUsage", "total used free")


@pytest.fixture
def fake_env(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(internal_logs.redis_client, "redis", fake)
    monkeypatch.setattr(
        internal_logs.shutil, "disk_usage",
        lambda _p: DiskUsage(100 * 1024 ** 3, 50 * 1024 ** 3, 50 * 1024 ** 3),
    )
    monkeypatch.setattr(settings, "RAW_LOGS_MAX_PER_HOUR", 1000)
    monkeypatch.setattr(settings, "RAW_LOGS_MIN_FREE_DISK_GB", 8.0)
    return fake


def test_budget_within_limit(fake_env):
    assert asyncio.run(internal_logs._raw_budget(400)) == 400
    assert asyncio.run(internal_logs._raw_budget(400)) == 400


def test_budget_cuts_at_hour_limit(fake_env):
    assert asyncio.run(internal_logs._raw_budget(900)) == 900
    assert asyncio.run(internal_logs._raw_budget(300)) == 100
    assert asyncio.run(internal_logs._raw_budget(50)) == 0


def test_budget_zero_when_disk_low(fake_env, monkeypatch):
    monkeypatch.setattr(
        internal_logs.shutil, "disk_usage",
        lambda _p: DiskUsage(100 * 1024 ** 3, 95 * 1024 ** 3, 5 * 1024 ** 3),
    )
    assert asyncio.run(internal_logs._raw_budget(10)) == 0


def test_budget_without_redis_still_writes(monkeypatch):
    monkeypatch.setattr(internal_logs.redis_client, "redis", None)
    monkeypatch.setattr(
        internal_logs.shutil, "disk_usage",
        lambda _p: DiskUsage(100 * 1024 ** 3, 50 * 1024 ** 3, 50 * 1024 ** 3),
    )
    assert asyncio.run(internal_logs._raw_budget(10)) == 10
