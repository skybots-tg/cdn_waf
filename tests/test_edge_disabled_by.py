"""
Кто выключил edge-ноду: человек или автоматика.

Выключенную в панели ноду health check возвращал в DNS через пару минут:
агент продолжал слать heartbeat, а свежий heartbeat считался признаком
автовыключения. Теперь это решает колонка `disabled_by`: 'manual' ставит
панель, 'auto' — health check, и возвращает он только свои.

Ноды живут в настоящей SQLite-таблице, чтобы фильтры запросов проверялись
по-честному, а не подыгрывающим фейком.
"""

import asyncio
import importlib.util
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

for _key, _value in {
    "SECRET_KEY": "test-secret",
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db",
    "REDIS_URL": "redis://localhost:6379/0",
    "CELERY_BROKER_URL": "redis://localhost:6379/1",
    "CELERY_RESULT_BACKEND": "redis://localhost:6379/2",
    "JWT_SECRET_KEY": secrets.token_hex(32),  # слабый секрет валидатор отвергает
    "ACME_EMAIL": "test@example.com",
}.items():
    os.environ.setdefault(_key, _value)

from alembic.migration import MigrationContext  # noqa: E402
from alembic.operations import Operations  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.models  # noqa: E402,F401  все модели, иначе мапперы не соберутся
from app.api.v1 import edge_nodes as edge_api  # noqa: E402
from app.models.edge_node import EdgeNode  # noqa: E402
from app.schemas.edge_node import EdgeNodeCreate, EdgeNodeUpdate  # noqa: E402
from app.services.edge_service import EdgeNodeService  # noqa: E402
from app.tasks import edge_health_tasks as eht  # noqa: E402

HEALTHY = (True, False, 10, True, "")
NO_TLS = (True, False, 10, False, "сертификат example.com истёк 2026-01-01")


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, expire=None):
        self.data[key] = value

    async def delete(self, key):
        self.data.pop(key, None)


class FakeAlerts:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        async def record(*args):
            self.calls.append((name, args))
        return record

    def named(self, name):
        return [args for called, args in self.calls if called == name]


class SQLiteSession:
    """Синхронная SQLite-сессия с тем кусочком AsyncSession, который нужен коду."""

    def __init__(self, session):
        self.sync = session

    async def execute(self, stmt):
        return self.sync.execute(stmt)

    async def commit(self):
        self.sync.commit()

    async def refresh(self, obj):
        self.sync.refresh(obj)

    def add(self, obj):
        self.sync.add(obj)

    def node(self, node_id, *, enabled=True, disabled_by=None):
        """Нода с живым агентом: heartbeat пришёл только что, статус online."""
        node = EdgeNode(
            id=node_id, name=f"node-{node_id}", ip_address=f"10.0.0.{node_id}",
            location_code="RU-MSK", enabled=enabled, disabled_by=disabled_by,
            status="online", last_heartbeat=datetime.utcnow() - timedelta(seconds=10),
        )
        self.sync.add(node)
        self.sync.commit()
        return node


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://")
    EdgeNode.__table__.create(engine)
    session = Session(engine)
    db = SQLiteSession(session)
    no_tls: set[int] = set()
    probed, synced = [], []

    async def probe(node, _hostnames):
        probed.append(node.id)
        return NO_TLS if node.id in no_tls else HEALTHY

    async def nothing(*_args, **_kwargs):
        return []

    import app.tasks.dns_tasks

    sync_task = SimpleNamespace(delay=lambda: synced.append(1))
    monkeypatch.setattr(app.tasks.dns_tasks, "sync_dns_nodes", sync_task)
    monkeypatch.setattr(edge_api, "sync_dns_nodes", sync_task)
    monkeypatch.setattr(eht, "_probe_edge_node", probe)
    monkeypatch.setattr(eht, "_edge_tls_sample", nothing)

    alerts = FakeAlerts()

    def recover():
        asyncio.run(eht._check_auto_disabled_recovery(db, alerts))

    def patch(node_id, **fields):
        return asyncio.run(edge_api.update_edge_node(
            node_id, EdgeNodeUpdate(**fields), db=db, current_user=None,
        ))

    yield SimpleNamespace(db=db, no_tls=no_tls, probed=probed, synced=synced,
                          alerts=alerts, recover=recover, patch=patch)
    session.close()
    engine.dispose()


def test_manual_disable_survives_recovery_while_agent_is_alive(env):
    """Сам баг: агент жив и шлёт heartbeat, но выключили руками — не возвращаем."""
    node = env.db.node(1)

    env.patch(1, enabled=False)
    assert (node.enabled, node.disabled_by) == (False, "manual")

    env.recover()

    assert (node.enabled, node.disabled_by) == (False, "manual")
    assert env.probed == []
    assert env.alerts.named("edge_node_recovered") == []


def test_auto_disabled_node_comes_back_when_healthy(env):
    node = env.db.node(1)

    asyncio.run(eht._auto_disable_edge(env.db, FakeRedis(), env.alerts, node, 3, "HTTP check failed"))
    assert (node.enabled, node.disabled_by, node.status) == (False, "auto", "offline")

    env.recover()

    assert (node.enabled, node.disabled_by, node.status) == (True, None, "online")
    assert env.synced == [1]
    assert len(env.alerts.named("edge_node_recovered")) == 1


def test_auto_disabled_node_without_tls_stays_out(env):
    node = env.db.node(1, enabled=False, disabled_by="auto")
    env.no_tls.add(1)

    env.recover()

    assert (node.enabled, node.disabled_by) == (False, "auto")
    assert env.probed == [1]
    assert env.synced == []


def test_disabled_node_without_mark_counts_as_manual(env):
    """NULL у выключенной ноды — спорный случай из времён до миграции: не трогаем."""
    node = env.db.node(1, enabled=False, disabled_by=None)

    env.recover()

    assert not node.enabled
    assert env.probed == []


def test_manual_enable_clears_auto_mark(env):
    node = env.db.node(1, enabled=False, disabled_by="auto")

    env.patch(1, enabled=True)

    assert (node.enabled, node.disabled_by) == (True, None)


def test_edit_without_enabled_keeps_the_mark(env):
    node = env.db.node(1, enabled=False, disabled_by="auto")

    env.patch(1, name="renamed")

    assert (node.name, node.disabled_by) == ("renamed", "auto")


def test_saving_disabled_node_with_enabled_false_pins_it_manual(env):
    """Формы панели всегда шлют enabled. Сохранил выключенной — значит, решил человек."""
    node = env.db.node(1, enabled=False, disabled_by="auto")

    env.patch(1, name="renamed", enabled=False)

    assert node.disabled_by == "manual"
    env.recover()
    assert not node.enabled


def test_node_created_disabled_is_manual(env):
    node = asyncio.run(EdgeNodeService.create_node(env.db, EdgeNodeCreate(
        name="new", ip_address="10.0.0.9", location_code="RU-MSK", enabled=False,
    )))

    assert node.disabled_by == "manual"


def test_toggle_triggers_dns_sync(env):
    env.db.node(1)

    env.patch(1, enabled=False)
    assert env.synced == [1]

    env.patch(1, enabled=True)
    assert env.synced == [1, 1]


def test_dns_sync_only_when_dns_visible_fields_change(env):
    env.db.node(1)

    env.patch(1, name="renamed", enabled=True)  # форма пересылает enabled как есть
    assert env.synced == []

    env.patch(1, ip_address="10.0.0.99")
    assert env.synced == [1]


def test_patch_unknown_node_is_404(env):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        env.patch(404, enabled=False)
    assert exc.value.status_code == 404
    assert env.synced == []


def _load_migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0004_add_edge_nodes_disabled_by.py"
    spec = importlib.util.spec_from_file_location("migration_0004", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_marks_already_disabled_nodes_manual():
    migration = _load_migration()
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE edge_nodes (id INTEGER PRIMARY KEY, enabled BOOLEAN NOT NULL)"))
        conn.execute(text("INSERT INTO edge_nodes (id, enabled) VALUES (1, 1), (2, 0)"))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        rows = conn.execute(text("SELECT id, disabled_by FROM edge_nodes ORDER BY id")).all()
    engine.dispose()

    assert [tuple(r) for r in rows] == [(1, None), (2, "manual")]
