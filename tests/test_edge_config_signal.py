"""
Правка настроек домена поднимает config_version edge-нод.

До 23.09.2026 правило кэша, созданное в панели, до нод не доходило: версию
поднимали только здоровье origin и сертификаты, а сигнал службы кэша уходил
в Redis-канал без слушателей. Обратная ошибка — подъём версии от каждой
записи проверки здоровья — тоже проверяется: здоровье пишется каждые 30 с.
"""

import os
import secrets

import pytest

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

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.models  # noqa: E402,F401  все модели и слушатель edge_signal
from app.core.database import Base  # noqa: E402
from app.models.cache import CacheRule, CacheRuleType  # noqa: E402
from app.models.edge_node import EdgeNode  # noqa: E402
from app.models.origin import Origin  # noqa: E402


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[
        EdgeNode.__table__, CacheRule.__table__, Origin.__table__,
    ])
    session = Session(engine)
    for node_id in (1, 2):
        session.add(EdgeNode(
            id=node_id, name=f"node-{node_id}", ip_address=f"10.0.0.{node_id}",
            location_code="RU-MSK", config_version=5,
        ))
    session.add(Origin(id=1, domain_id=1, name="main", origin_host="198.51.100.1",
                       origin_port=80, protocol="http"))
    session.commit()
    # Отправная точка — версия после подготовки, её тоже поднял origin.
    session.execute(EdgeNode.__table__.update().values(config_version=5))
    session.commit()
    yield session
    session.close()


def versions(db):
    db.expire_all()
    return [n.config_version for n in db.scalars(select(EdgeNode).order_by(EdgeNode.id))]


def test_new_cache_rule_reaches_every_node(db):
    db.add(CacheRule(domain_id=1, pattern="^/static/", rule_type=CacheRuleType.CACHE, ttl=600))
    db.commit()
    assert versions(db) == [6, 6]


def test_rule_edit_and_delete_bump(db):
    rule = CacheRule(domain_id=1, pattern="^/static/", rule_type=CacheRuleType.CACHE, ttl=600)
    db.add(rule)
    db.commit()
    rule.ttl = 60
    db.commit()
    db.delete(rule)
    db.commit()
    assert versions(db) == [8, 8]


def test_origin_health_writes_do_not_bump(db):
    origin = db.get(Origin, 1)
    origin.health_status = "unhealthy"
    origin.consecutive_failures = 3
    db.commit()
    assert versions(db) == [5, 5]


def test_origin_address_change_bumps(db):
    db.get(Origin, 1).origin_host = "198.51.100.2"
    db.commit()
    assert versions(db) == [6, 6]


def test_node_heartbeat_does_not_bump(db):
    db.get(EdgeNode, 1).status = "online"
    db.commit()
    assert versions(db) == [5, 5]


class FakeRedis:
    def __init__(self, keys=()):
        self.data = {key: "1" for key in keys}

    async def exists(self, key):
        return int(key in self.data)

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value):
        self.data[key] = value


class AsyncWrap:
    """Синхронная SQLite-сессия под видом AsyncSession."""

    def __init__(self, session):
        self.sync = session

    async def execute(self, stmt):
        return self.sync.execute(stmt)

    async def commit(self):
        self.sync.commit()


def test_dev_mode_change_bumps_once(db):
    import asyncio

    from app.models.domain import Domain
    from app.tasks.edge_tasks import sync_dev_mode_state

    Domain.__table__.create(db.get_bind())
    db.execute(Domain.__table__.insert().values(id=7, organization_id=1, name="example.com",
                                                status="ACTIVE", ns_verified=False))
    db.commit()
    redis = FakeRedis({"dev_mode:7"})
    run = lambda: asyncio.run(sync_dev_mode_state(AsyncWrap(db), redis))  # noqa: E731

    assert run()["changed"] is True      # режим включили — ноды перестают кэшировать
    assert run()["changed"] is False     # ничего не поменялось — версию не трогаем
    del redis.data["dev_mode:7"]         # срок истёк, ключ исчез сам
    assert run() == {"changed": True, "active": []}
    assert versions(db) == [7, 7]
