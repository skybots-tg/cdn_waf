"""
Резервные edge-ноды (BACKUP_EDGE_IPS) и выдача DNS.

DNS-нода отвечает всеми edge-нодами, которые приехали в снапшоте enabled и
online, — своего понятия «резерв» у неё нет. Поэтому уровень назначает панель
при сборке снапшота: пока жива хотя бы одна основная нода, резервные уезжают
выключенными; не осталось основных — резервные возвращаются в выдачу сами.

Повод (22–23.09.2026): через ноды TimeWeb статика мини-приложения грузилась
8–16 с против 1–2 с через остальные, и людям в Алматы открывался белый экран.
"""

import os
import secrets

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

from app.core.config import settings  # noqa: E402
from app.services.dns_sync_service import apply_backup_tier  # noqa: E402

PRIMARY_A = "80.87.197.79"
PRIMARY_B = "45.150.238.245"
BACKUP_A = "37.252.21.181"
BACKUP_B = "213.171.4.136"


def _node(ip, enabled=True, status="online"):
    return {"ip_address": ip, "enabled": enabled, "status": status}


def _visible(rows):
    """Какие адреса отдаст DNS-нода: ровно её условие enabled + online."""
    return [r["ip_address"] for r in rows if r["enabled"] and r["status"] == "online"]


@pytest.fixture
def backups(monkeypatch):
    monkeypatch.setattr(settings, "BACKUP_EDGE_IPS", f"{BACKUP_A}, {BACKUP_B}")


def _fleet(**overrides):
    rows = [_node(PRIMARY_A), _node(PRIMARY_B), _node(BACKUP_A), _node(BACKUP_B)]
    return [dict(r, **overrides.get(r["ip_address"], {})) for r in rows]


def test_backups_hidden_while_primary_online(backups):
    assert _visible(apply_backup_tier(_fleet())) == [PRIMARY_A, PRIMARY_B]


def test_one_primary_left_is_enough(backups):
    rows = _fleet(**{PRIMARY_A: {"status": "offline"}})
    assert _visible(apply_backup_tier(rows)) == [PRIMARY_B]


def test_backups_return_when_no_primary(backups):
    rows = _fleet(**{
        PRIMARY_A: {"status": "offline"},
        PRIMARY_B: {"enabled": False},
    })
    assert _visible(apply_backup_tier(rows)) == [BACKUP_A, BACKUP_B]


def test_disabled_backup_stays_disabled(backups):
    """Вручную выключенную резервную ноду не включаем даже при аварии основных."""
    rows = _fleet(**{
        PRIMARY_A: {"status": "offline"},
        PRIMARY_B: {"status": "offline"},
        BACKUP_B: {"enabled": False},
    })
    assert _visible(apply_backup_tier(rows)) == [BACKUP_A]


def test_db_rows_are_not_mutated(backups):
    """Уровень меняет только снапшот: строки из БД остаются как есть."""
    rows = _fleet()
    apply_backup_tier(rows)
    assert all(r["enabled"] for r in rows)


def test_empty_setting_keeps_old_behaviour(monkeypatch):
    monkeypatch.setattr(settings, "BACKUP_EDGE_IPS", "")
    assert _visible(apply_backup_tier(_fleet())) == [
        PRIMARY_A, PRIMARY_B, BACKUP_A, BACKUP_B,
    ]
