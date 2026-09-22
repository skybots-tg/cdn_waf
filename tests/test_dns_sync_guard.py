"""
Тесты защиты DNS-синка от пустого или урезанного снапшота.

Нода делает TRUNCATE и заливает снапшот панели целиком. Пустой снапшот (баг,
полувосстановленная БД панели, пустой ответ Postgres) стёр бы зоны на всех
нодах разом. Здесь проверяется, что такой снапшот отвергают и нода (409, таблицы
не тронуты), и панель (до отправки), что об этом узнают из лога и Telegram, что
force его всё же применяет и что авторизация синка осталась прежней.

Панель ходит в настоящий FastAPI-эндпоинт ноды через ASGITransport; под ним —
фейковая БД ноды, понимающая ровно те запросы, что шлёт приём снапшота.
"""

import asyncio
import os
import secrets
from datetime import datetime
from types import SimpleNamespace

import httpx
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

from fastapi.testclient import TestClient  # noqa: E402

from app import dns_server  # noqa: E402
from app.schemas.sync import (  # noqa: E402
    DNSNodeSync, DNSRecordSync, DNSSyncPayload, DomainSync, EdgeNodeSync,
    OrganizationSync, UserSync,
)
from app.services import dns_sync_service as dss  # noqa: E402
from app.services.dns_sync_guard import SnapshotCounts, snapshot_problem  # noqa: E402

TOKEN = "node-token"
NOW = datetime(2026, 1, 1)
TABLE_SCHEMAS = {
    "users": UserSync,
    "organizations": OrganizationSync,
    "domains": DomainSync,
    "dns_records": DNSRecordSync,
    "edge_nodes": EdgeNodeSync,
    "dns_nodes": DNSNodeSync,
}


def make_payload(domains: int, records: int) -> DNSSyncPayload:
    stamps = {"created_at": NOW, "updated_at": NOW}
    return DNSSyncPayload(
        users=[UserSync(id=1, email="a@example.com", is_active=True, is_superuser=True, **stamps)],
        organizations=[OrganizationSync(id=1, name="org", owner_id=1, **stamps)],
        domains=[
            DomainSync(id=i, organization_id=1, name=f"d{i}.ru", status="active",
                       ns_verified=True, **stamps)
            for i in range(1, domains + 1)
        ],
        records=[
            DNSRecordSync(id=i, domain_id=i % max(domains, 1) + 1, type="A", name="@",
                          content="192.0.2.1", ttl=300, proxied=False, **stamps)
            for i in range(1, records + 1)
        ],
        edge_nodes=[EdgeNodeSync(id=1, name="edge", ip_address="192.0.2.10", location_code="RU",
                                 country_code="RU", enabled=True, status="online", **stamps)],
        dns_nodes=[DNSNodeSync(id=1, name="ns1", hostname="ns1.example.ru",
                               ip_address="192.0.2.53", location_code="RU", enabled=True, **stamps)],
    )


def table_rows(payload: DNSSyncPayload) -> dict[str, list[dict]]:
    return {
        "users": [r.model_dump() for r in payload.users],
        "organizations": [r.model_dump() for r in payload.organizations],
        "domains": [r.model_dump() for r in payload.domains],
        "dns_records": [r.model_dump() for r in payload.records],
        "edge_nodes": [r.model_dump() for r in payload.edge_nodes],
        "dns_nodes": [r.model_dump() for r in payload.dns_nodes],
    }


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self.rows))

    def scalar(self):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


class FakeNodeDB:
    """Postgres DNS-ноды: только запросы из app/dns_node_sync.py."""

    def __init__(self, tables: dict[str, list[dict]]):
        self.tables = tables
        self.statements: list[str] = []
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        pass

    def commit(self):
        self.commits += 1

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.statements.append(sql)
        if "pg_advisory_xact_lock" in sql:
            return Result()
        if "FROM pg_tables" in sql:
            return Result(self.tables)
        if sql.startswith("SELECT count(*) FROM"):
            return Result([len(self.tables[sql.split()[-1]])])
        if "information_schema.columns" in sql:
            return Result((c,) for c in TABLE_SCHEMAS[params["table_name"]].model_fields)
        if sql.startswith("TRUNCATE TABLE"):
            for table in sql[len("TRUNCATE TABLE "):].split(" RESTART")[0].split(", "):
                self.tables[table] = []
            return Result()
        if sql.startswith("INSERT INTO"):
            self.tables[sql.split()[2]].extend(params)
            return Result()
        raise AssertionError(f"unexpected SQL: {sql}")

    def counts(self):
        return len(self.tables["domains"]), len(self.tables["dns_records"])

    def truncated(self):
        return any(s.startswith("TRUNCATE") for s in self.statements)


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    async def delete(self, *keys):
        for key in keys:
            self.data.pop(key, None)

    async def aclose(self):
        pass


class BrokenRedis(FakeRedis):
    async def get(self, key):
        raise ConnectionError("redis down")

    async def set(self, key, value, ex=None, nx=False):
        raise ConnectionError("redis down")

    async def delete(self, *keys):
        raise ConnectionError("redis down")


class FakeAlerts:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        async def record(*args):
            self.calls.append((name, args))
        return record

    def named(self, name):
        return [args for called, args in self.calls if called == name]


@pytest.fixture
def node_db(monkeypatch):
    """DNS-нода с 10 доменами и 100 записями, синк защищён токеном."""
    db = FakeNodeDB(table_rows(make_payload(10, 100)))
    monkeypatch.setattr(dns_server, "SessionLocal", lambda: db)
    monkeypatch.setattr(dns_server.settings, "NODE_SYNC_TOKEN", TOKEN)
    return db


@pytest.fixture
def node_api(node_db):
    client = TestClient(dns_server.app)

    def post(payload, token=TOKEN, **params):
        headers = {"X-Node-Token": token} if token else {}
        return client.post("/api/v1/sync", json=payload.model_dump(mode="json"),
                           params=params, headers=headers)

    return post


@pytest.fixture
def panel(monkeypatch, node_db):
    """Панель, которая шлёт снапшот в настоящий эндпоинт ноды node_db."""
    state = SimpleNamespace(payload=make_payload(10, 100), redis=FakeRedis(), alerts=FakeAlerts())
    node = SimpleNamespace(id=1, name="ns1", ip_address="192.0.2.53", last_sync_at=None)

    async def build(_db):
        return state.payload

    async def commit():
        pass

    monkeypatch.setattr(dss, "build_sync_payload", build)
    monkeypatch.setattr(dss, "_http_client",
                        lambda: httpx.AsyncClient(transport=httpx.ASGITransport(app=dns_server.app)))
    monkeypatch.setattr(dss, "_open_redis", lambda: state.redis)
    monkeypatch.setattr(dss, "AlertService", state.alerts)

    def sync(force=False):
        return asyncio.run(dss.sync_node(node, SimpleNamespace(commit=commit), force=force))

    state.node, state.sync = node, sync
    return state


# ---- правила ----

@pytest.mark.parametrize("incoming, current, refused", [
    ((0, 0), (10, 100), True),     # пустой снапшот
    ((10, 0), (10, 100), True),    # домены есть, записей нет
    ((0, 50), (10, 100), True),    # записи есть, доменов нет
    ((4, 100), (10, 100), True),   # −60% доменов
    ((10, 40), (10, 100), True),   # −60% записей
    ((5, 50), (10, 100), False),   # ровно −50% — ещё можно
    ((9, 95), (10, 100), False),   # обычное удаление
    ((12, 130), (10, 100), False), # рост
    ((0, 0), (0, 0), False),       # пустая нода, сравнивать не с чем
    ((3, 0), (0, 0), False),       # первый синк
])
def test_snapshot_problem(incoming, current, refused):
    problem = snapshot_problem(SnapshotCounts(*incoming), SnapshotCounts(*current))
    assert (problem is not None) == refused


# ---- нода ----

def test_node_refuses_empty_snapshot_and_keeps_zones(node_api, node_db):
    resp = node_api(make_payload(0, 0))

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error"] == "snapshot_rejected"
    assert "0 доменов" in detail["reason"]
    assert detail["current"] == {"domains": 10, "records": 100}
    assert detail["incoming"] == {"domains": 0, "records": 0}
    assert node_db.counts() == (10, 100)
    assert not node_db.truncated() and node_db.commits == 0


@pytest.mark.parametrize("domains, records", [(10, 0), (4, 100), (10, 40)])
def test_node_refuses_gutted_snapshot(node_api, node_db, domains, records):
    resp = node_api(make_payload(domains, records))

    assert resp.status_code == 409
    assert node_db.counts() == (10, 100)
    assert not node_db.truncated()


def test_node_applies_normal_snapshot(node_api, node_db):
    resp = node_api(make_payload(9, 95))

    assert resp.status_code == 200
    assert node_db.counts() == (9, 95)
    assert node_db.commits == 1
    # Лок до подсчёта: иначе два синка ждут друг друга на TRUNCATE (deadlock).
    assert "pg_advisory_xact_lock" in node_db.statements[0]


def test_node_force_applies_refused_snapshot(node_api, node_db):
    resp = node_api(make_payload(0, 0), force="true")

    assert resp.status_code == 200
    assert node_db.counts() == (0, 0)


def test_fresh_node_accepts_first_snapshot(node_api, node_db):
    for table in node_db.tables:
        node_db.tables[table] = []

    assert node_api(make_payload(3, 7)).status_code == 200
    assert node_db.counts() == (3, 7)


@pytest.mark.parametrize("token", [None, "wrong"])
def test_auth_is_checked_before_anything(node_api, node_db, token):
    resp = node_api(make_payload(0, 0), token=token, force="true")

    assert resp.status_code == 401
    assert node_db.statements == [] and node_db.counts() == (10, 100)


# ---- панель ----

def test_panel_sync_remembers_accepted_snapshot(panel, node_db):
    res = panel.sync()

    assert res.success and res.exit_code == 0
    assert panel.node.last_sync_at is not None
    assert panel.redis.data[dss.LAST_ACCEPTED_KEY] == '{"domains": 10, "records": 100}'
    assert panel.alerts.calls == []


def test_panel_does_not_send_empty_snapshot(panel, node_db, caplog):
    panel.sync()
    node_db.statements.clear()
    panel.payload = make_payload(0, 0)

    results = [panel.sync() for _ in range(3)]

    assert all(not r.success and r.exit_code == dss.SYNC_REFUSED_EXIT_CODE for r in results)
    assert "panel guard" in results[0].stderr and "0 доменов" in results[0].stderr
    assert node_db.statements == []  # на ноду ничего не ушло
    assert node_db.counts() == (10, 100)
    alerts = panel.alerts.named("dns_sync_refused")
    assert len(alerts) == 1  # кулдаун
    assert "панель" in alerts[0][0]
    assert "Snapshot refused by panel guard" in caplog.text


def test_node_refusal_is_logged_and_alerted(panel, node_db, caplog):
    """Панель не знает прошлого снапшота (Redis пуст) — ловит сама нода."""
    panel.payload = make_payload(3, 100)

    res = panel.sync()

    assert not res.success and res.exit_code == dss.SYNC_REFUSED_EXIT_CODE
    assert "node guard" in res.stderr and "доменов в снапшоте 3 вместо 10" in res.stderr
    assert node_db.counts() == (10, 100)
    assert panel.node.last_sync_at is None
    assert dss.LAST_ACCEPTED_KEY not in panel.redis.data
    [(where, reason)] = panel.alerts.named("dns_sync_refused")
    assert "ns1" in where and "3 вместо 10" in reason
    assert "Snapshot refused by node guard" in caplog.text


def test_force_skips_both_guards(panel, node_db):
    panel.sync()
    panel.payload = make_payload(0, 0)
    panel.sync()  # отказ, алерт и кулдаун

    res = panel.sync(force=True)

    assert res.success
    assert node_db.counts() == (0, 0)
    assert panel.redis.data[dss.LAST_ACCEPTED_KEY] == '{"domains": 0, "records": 0}'
    assert dss.PANEL_ALERT_KEY not in panel.redis.data


def test_panel_without_redis_still_protected_by_node(panel, node_db):
    panel.redis = BrokenRedis()
    panel.payload = make_payload(0, 0)

    results = [panel.sync() for _ in range(2)]

    assert all(r.exit_code == dss.SYNC_REFUSED_EXIT_CODE for r in results)
    assert node_db.counts() == (10, 100)
    assert len(panel.alerts.named("dns_sync_refused")) == 2  # без Redis — без кулдауна
