"""
Тесты защиты автоотключения edge-нод.

Проверки идут из одной точки — с панели. Если сломалась сама проверка (у панели
пропал интернет, лёг cdn_app и не доходят heartbeat'ы), мёртвыми выглядят все
ноды сразу. Выключить их все значит отдать в DNS origin-адреса мимо CDN/WAF.
Здесь проверяется, что такой раунд не выключает никого, одиночный сбой
по-прежнему выключает ноду, а число включённых нод не падает ниже минимума.
"""

import asyncio
import os
import secrets
from contextlib import asynccontextmanager
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

from app.tasks import edge_health_tasks as eht  # noqa: E402
from app.tasks.edge_health_guard import (  # noqa: E402
    can_auto_disable,
    checker_is_online,
    is_mass_failure,
)

HEALTHY = (True, False, 10, True, "")
DEAD = (False, True, 900, False, "TLS до example.com не установлен (TimeoutError)")


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def connect(self):
        pass

    async def disconnect(self):
        pass

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


class FakeDB:
    def __init__(self, nodes):
        self.nodes = nodes

    async def execute(self, _stmt):
        enabled = [n for n in self.nodes if n.enabled]
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: enabled))

    async def commit(self):
        pass


@pytest.fixture
def cluster(monkeypatch):
    """Четыре включённые ноды и подменённое окружение одного раунда проверки."""
    nodes = [
        SimpleNamespace(id=i, name=f"node-{i}", ip_address=f"10.0.0.{i}",
                        enabled=True, status="online")
        for i in range(1, 5)
    ]
    dead_ids: set[int] = set()
    redis, alerts, synced = FakeRedis(), FakeAlerts(), []
    db = FakeDB(nodes)

    @asynccontextmanager
    async def session():
        yield db

    async def dispose():
        pass

    async def probe(node, _hostnames):
        return DEAD if node.id in dead_ids else HEALTHY

    async def nothing(*_args, **_kwargs):
        return []

    async def online():
        return True

    import app.core.redis
    import app.services.alert_service
    import app.tasks.dns_tasks

    monkeypatch.setattr(app.core.redis, "redis_client", redis)
    monkeypatch.setattr(app.services.alert_service, "AlertService", alerts)
    monkeypatch.setattr(app.tasks.dns_tasks, "sync_dns_nodes",
                        SimpleNamespace(delay=lambda: synced.append(1)))
    monkeypatch.setattr(eht, "create_task_db_session",
                        lambda: (SimpleNamespace(dispose=dispose), session))
    monkeypatch.setattr(eht, "_probe_edge_node", probe)
    monkeypatch.setattr(eht, "_edge_tls_sample", nothing)
    monkeypatch.setattr(eht, "_check_auto_disabled_recovery", nothing)
    monkeypatch.setattr(eht, "checker_is_online", online)

    def run_rounds(count):
        return [asyncio.run(eht._check_edge_nodes_health_async()) for _ in range(count)]

    return SimpleNamespace(nodes=nodes, dead=dead_ids, redis=redis,
                           alerts=alerts, synced=synced, run=run_rounds)


def test_mass_failure_is_more_than_half():
    assert not is_mass_failure(1, 4)
    assert not is_mass_failure(2, 4)
    assert is_mass_failure(3, 4)
    assert is_mass_failure(2, 3)
    assert not is_mass_failure(0, 0)


def test_auto_disable_keeps_two_nodes():
    assert can_auto_disable(3)
    assert not can_auto_disable(2)


def test_single_dead_node_is_disabled_after_threshold(cluster):
    cluster.dead.add(1)

    results = cluster.run(eht.EDGE_FAILURE_THRESHOLD)

    assert not cluster.nodes[0].enabled
    assert cluster.nodes[0].disabled_by == "auto"
    assert all(n.enabled for n in cluster.nodes[1:])
    assert results[-1]["disabled_any"] and not results[-1]["mass_failure"]
    assert cluster.synced == [1]
    assert len(cluster.alerts.named("edge_node_disabled")) == 1


def test_mass_failure_disables_nobody(cluster):
    """Три из четырёх нод «упали» разом — проверке не верим, все остаются в DNS."""
    cluster.dead.update({1, 2, 3})

    results = cluster.run(eht.EDGE_FAILURE_THRESHOLD + 2)

    assert all(n.enabled for n in cluster.nodes)
    assert all(r["mass_failure"] and not r["disabled_any"] for r in results)
    assert cluster.synced == []
    assert not any(k.startswith("edge:failures:") for k in cluster.redis.data)
    assert len(cluster.alerts.named("edge_mass_failure")) == 1  # cooldown
    assert cluster.alerts.named("edge_node_down") == []
    assert cluster.alerts.named("edge_node_disabled") == []


def test_counting_restarts_after_mass_failure(cluster):
    """Раунды массового сбоя не копят счётчик: после них нода не выключается сразу."""
    cluster.dead.update({1, 2, 3})
    cluster.run(eht.EDGE_FAILURE_THRESHOLD)

    cluster.dead.clear()
    cluster.dead.add(1)
    cluster.run(eht.EDGE_FAILURE_THRESHOLD - 1)
    assert cluster.nodes[0].enabled

    cluster.run(1)
    assert not cluster.nodes[0].enabled


def test_never_disables_below_minimum(cluster):
    """Ноды умирают по одной: выключаем, пока не останется две, дальше держим."""
    cluster.dead.update({1, 2})
    cluster.run(eht.EDGE_FAILURE_THRESHOLD)
    assert [n.enabled for n in cluster.nodes] == [False, False, True, True]
    assert cluster.synced == [1]

    cluster.dead.add(3)
    cluster.run(eht.EDGE_FAILURE_THRESHOLD + 2)

    assert [n.enabled for n in cluster.nodes] == [False, False, True, True]
    assert cluster.synced == [1]
    kept = cluster.alerts.named("edge_node_down")
    assert kept and "оставлена в ротации" in kept[-1][2]


def test_checker_online_when_any_target_answers():
    async def scenario():
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        closed = await _closed_port()
        try:
            ok = await checker_is_online((("127.0.0.1", closed), ("127.0.0.1", port)), 2)
            down = await checker_is_online((("127.0.0.1", closed),), 2)
        finally:
            server.close()
            await server.wait_closed()
        return ok, down

    ok, down = asyncio.run(scenario())
    assert ok and not down


async def _closed_port() -> int:
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()
    return port
