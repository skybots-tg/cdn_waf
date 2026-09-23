"""Правка настроек домена сама доходит до edge-нод.

Нода забирает конфиг, только когда у неё вырос ``config_version``
(app/api/internal.py: get_edge_config). До 23.09.2026 правила кэша, WAF,
лимиты, origin и TLS меняли только свои таблицы: версию поднимали лишь смена
здоровья origin и выпуск сертификата, а служба кэша публиковала событие в
Redis, которое никто не слушал. Правило из панели висело неприменённым, пока
не случалось что-то постороннее.

Теперь запись этих настроек в той же транзакции поднимает версию всех нод.
Лишний подъём дёшев: агент сравнивает отрисованный конфиг с текущим и без
разницы nginx не перезагружает.
"""
from sqlalchemy import event, func, inspect, update
from sqlalchemy.orm import Session

from app.models.cache import CacheRule
from app.models.dns import DNSRecord
from app.models.domain import Domain, DomainTLSSettings
from app.models.edge_node import EdgeNode
from app.models.origin import Origin
from app.models.waf import IPAccessRule, RateLimit, WAFRule

_ALL = object()

#: Модель → колонки, которые попадают в конфиг ноды (_ALL — все, кроме времени правки).
WATCHED = {
    CacheRule: _ALL,
    WAFRule: _ALL,
    RateLimit: _ALL,
    IPAccessRule: _ALL,
    DomainTLSSettings: _ALL,
    DNSRecord: _ALL,
    # Здоровье origin пишется каждые полминуты, и его смену версия получает в
    # health_tasks. Здесь — только то, что человек меняет в панели.
    Origin: {"domain_id", "origin_host", "origin_port", "protocol", "weight", "is_backup", "enabled"},
    Domain: {"name", "status"},
}
_TIMESTAMPS = {"created_at", "updated_at"}


def touches_config(obj, *, dirty: bool) -> bool:
    columns = WATCHED.get(type(obj))
    if columns is None:
        return False
    if not dirty:
        return True
    state = inspect(obj)
    for attr in state.mapper.column_attrs:
        key = attr.key
        if key in _TIMESTAMPS or (columns is not _ALL and key not in columns):
            continue
        if state.attrs[key].history.has_changes():
            return True
    return False


@event.listens_for(Session, "after_flush")
def _bump_edge_config(session, _flush_context):
    changed = (
        any(touches_config(obj, dirty=False) for obj in session.new)
        or any(touches_config(obj, dirty=False) for obj in session.deleted)
        or any(touches_config(obj, dirty=True) for obj in session.dirty)
    )
    if not changed:
        return
    nodes = EdgeNode.__table__
    session.connection().execute(
        update(nodes).values(config_version=func.coalesce(nodes.c.config_version, 0) + 1)
    )


async def bump_edge_config(db) -> None:
    """Поднять версию всех нод явно — для настроек, которые живут не в этих
    таблицах (режим разработки хранится в Redis)."""
    nodes = EdgeNode.__table__
    await db.execute(
        update(nodes).values(config_version=func.coalesce(nodes.c.config_version, 0) + 1)
    )
    await db.commit()
