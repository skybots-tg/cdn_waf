"""Internal API — log ingestion, ACME challenges, and file download for edge nodes."""
import hashlib
import logging
import shutil
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import String, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.core.redis import redis_client
from app.models.edge_node import EdgeNode
from app.models.domain import Domain, DomainStatus
from app.models.log import RequestLog
from app.services import ip_networks, traffic_class
from app.services.analytics_aggregation import DIRTY_HOURS_KEY

logger = logging.getLogger(__name__)

router = APIRouter()


def _as_int(value, default=None):
    """Целое из того, что прислала нода, или default.

    Nginx подставляет в лог пустую строку или дефис там, где переменной нет:
    так в status и waf_rule_id приходило "", и вставка партии логов
    падала целиком с 'str' object cannot be interpreted as an integer.
    Партия — это сотни строк от всех нод сразу, поэтому одна пустая переменная
    роняла приём логов у всех.
    """
    if value is None or value == "" or value == "-":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# Максимальные длины строковых колонок request_logs. Nginx присылает path,
# query_string, referer и user_agent любой длины (сканеры шлют URL на десятки
# килобайт), а колонки — VARCHAR(2048)/VARCHAR(512). Одна такая строка роняла
# INSERT всей партии (сотни записей от всех нод), нода повторяла отправку,
# а PostgreSQL на каждую попытку писал в лог полный текст запроса — ~2.5 ГБ/сутки.
_STR_LIMITS: Dict[str, int] = {
    col.name: col.type.length
    for col in RequestLog.__table__.columns
    if isinstance(col.type, String) and col.type.length
}


def _fit(value: Any, column: str) -> Optional[str]:
    """Приводит значение к строке и обрезает по длине колонки request_logs."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    limit = _STR_LIMITS.get(column)
    if limit and len(value) > limit:
        return value[:limit]
    return value


# verify_edge_node is defined in internal.py which imports us at the bottom,
# so by the time our endpoints are called, the function is fully available.
from app.api.internal import verify_edge_node


@router.post("/logs")
async def receive_logs(
    logs: List[Dict[str, Any]],
    node: EdgeNode = Depends(verify_edge_node),
    db: AsyncSession = Depends(get_db)
):
    """Принять партию строк access-лога от edge-ноды.

    Три правила, из-за которых приём 03.09.2026 выключали:

    * повтор безвреден — у строки отпечаток, вставка ON CONFLICT DO NOTHING.
      Нода шлёт партию снова, если не дождалась ответа за 10 с, и раньше
      каждая такая партия ложилась в таблицу ещё раз;
    * вставка одним пакетом, а не по строке через ORM: партия до 5000 строк
      должна укладываться в таймаут ноды с большим запасом;
    * при перегрузе строки отбрасываем, но отвечаем 200 (см. _raw_budget).

    Строки хостов, которых нет среди зон панели (сканеры бьют прямо по IP
    нод), не храним: для аналитики доменов это шум, а в таблице их было 78%.
    """
    if not logs:
        return {"status": "ok", "received": 0, "stored": 0}

    zones = await _zones(db)
    rows = []
    unmatched = 0
    for log_data in logs:
        host = _host_of(log_data.get("domain"))
        domain_id = _zone_for(host, zones)
        if domain_id is None:
            unmatched += 1
            continue
        rows.append(_row(log_data, node.id, domain_id, host))

    allowed = await _raw_budget(len(rows))
    dropped = len(rows) - allowed
    if dropped:
        rows = rows[:allowed]

    if rows:
        stmt = pg_insert(RequestLog.__table__).on_conflict_do_nothing(
            index_elements=["fingerprint"]
        )
        await db.execute(stmt, rows)
        await db.commit()

    await _count(unmatched=unmatched, dropped=dropped)
    if rows:
        await _mark_dirty_hours(rows)
    return {
        "status": "ok",
        "received": len(logs),
        "stored": len(rows),
        "unmatched": unmatched,
        "dropped": dropped,
        "timestamp": datetime.utcnow().isoformat(),
    }


# --- приём логов: вспомогательное ------------------------------------------

_ZONES_TTL = 60.0
_zones_cache: Dict[str, Any] = {"at": 0.0, "map": {}}


async def _zones(db: AsyncSession) -> Dict[str, int]:
    """Зоны панели: имя → id. Кэш на минуту — партии идут каждые пару секунд."""
    now = time.monotonic()
    if now - _zones_cache["at"] < _ZONES_TTL and _zones_cache["map"]:
        return _zones_cache["map"]
    result = await db.execute(
        select(Domain.id, Domain.name).where(Domain.status != DomainStatus.DELETED)
    )
    zones = {name.lower().rstrip("."): domain_id for domain_id, name in result.all()}
    _zones_cache.update(at=now, map=zones)
    return zones


def _host_of(value: Any) -> str:
    """Хост из поля лога: без порта, точки в конце и регистра."""
    host = str(value or "").strip().lower().rstrip(".")
    if host.startswith("["):  # IPv6 в квадратных скобках — это не зона
        return host
    return host.split(":", 1)[0]


def _zone_for(host: str, zones: Dict[str, int]) -> Optional[int]:
    """Зона хоста: самый длинный суффикс, совпавший с доменом панели.

    Нода пишет $host (app.example.com), а зона в панели — example.com. До
    23.09.2026 искали точное совпадение, и весь трафик поддоменов терял домен.
    """
    if not host:
        return None
    labels = host.split(".")
    for i in range(len(labels) - 1):
        zone_id = zones.get(".".join(labels[i:]))
        if zone_id is not None:
            return zone_id
    return None


_FINGERPRINT_FIELDS = (
    "timestamp", "domain", "client_ip", "method", "path", "status",
    "bytes_sent", "request_time", "user_agent", "referer",
)


def _fingerprint(node_id: int, log_data: Dict[str, Any]) -> int:
    """Отпечаток строки лога: одна и та же строка от той же ноды — тот же номер.

    Берём поля как их прислала нода, до разбора: разбор может поменяться, а
    отпечаток повторной партии обязан совпасть с первой.
    """
    raw = "\x1f".join(str(log_data.get(k, "")) for k in _FINGERPRINT_FIELDS)
    digest = hashlib.blake2b(
        f"{node_id}\x1f{raw}".encode("utf-8", "replace"), digest_size=8
    ).digest()
    return int.from_bytes(digest, "big", signed=True)


def _row(log_data: Dict[str, Any], node_id: int, domain_id: int, host: str) -> Dict[str, Any]:
    timestamp_str = log_data.get("timestamp")
    timestamp = datetime.utcnow()
    if timestamp_str:
        try:
            parsed = datetime.fromisoformat(str(timestamp_str).replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            timestamp = parsed
        except ValueError:
            pass

    raw_request_time = log_data.get("request_time")
    try:
        request_time_ms = (
            int(float(raw_request_time) * 1000) if raw_request_time not in (None, "", "-") else None
        )
    except (ValueError, TypeError):
        request_time_ms = None

    raw_path = str(log_data.get("path") or "/")
    path, _, query_string = raw_path.partition("?")

    cache_status = log_data.get("cache_status")
    if cache_status in ("", "-", None):
        cache_status = None

    client_ip = _fit(log_data.get("client_ip"), "client_ip")
    user_agent = _fit(log_data.get("user_agent") or None, "user_agent")
    status_code = _as_int(log_data.get("status"))
    asn, org = ip_networks.lookup(client_ip)
    client_class = traffic_class.classify(
        user_agent, path, status_code, ip_networks.is_hosting(asn, org)
    )

    return {
        "timestamp": timestamp,
        "domain_id": domain_id,
        "edge_node_id": node_id,
        "host": _fit(host, "host"),
        "fingerprint": _fingerprint(node_id, log_data),
        "method": _fit(log_data.get("method"), "method"),
        "path": _fit(path or "/", "path"),
        "query_string": _fit(query_string or None, "query_string"),
        "status_code": status_code,
        "bytes_sent": _as_int(log_data.get("bytes_sent"), 0),
        "client_ip": client_ip,
        "cache_status": _fit(cache_status, "cache_status"),
        "user_agent": user_agent,
        "referer": _fit(log_data.get("referer") or None, "referer"),
        "request_time": request_time_ms,
        "country_code": _fit(log_data.get("country_code") or None, "country_code"),
        "waf_status": _fit(log_data.get("waf_status") or None, "waf_status"),
        "waf_rule_id": _as_int(log_data.get("waf_rule_id")),
        "upstream_time": _upstream_ms(log_data.get("upstream_time")),
        "upstream_status": _upstream_status(log_data.get("upstream_status")),
        "bytes_received": _as_int(log_data.get("request_length")),
        "asn": asn,
        "client_class": client_class,
    }


def _upstream_parts(value: Any) -> List[str]:
    """Значения $upstream_* по попыткам: nginx пишет «0.012, 0.030» или «502 : 200»."""
    text = str(value or "").replace(":", ",")
    return [p.strip() for p in text.split(",") if p.strip() and p.strip() != "-"]


def _upstream_ms(value: Any) -> Optional[int]:
    """Время ответа origin в мс — сумма по попыткам; None, если до origin не ходили."""
    total = 0.0
    seen = False
    for part in _upstream_parts(value):
        try:
            total += float(part)
            seen = True
        except ValueError:
            continue
    return int(total * 1000) if seen else None


def _upstream_status(value: Any) -> Optional[int]:
    """Код последней попытки к origin — именно он ушёл клиенту."""
    parts = _upstream_parts(value)
    code = _as_int(parts[-1]) if parts else None
    return code if code is not None and 100 <= code <= 599 else None


def _hour_key(prefix: str) -> str:
    return f"analytics:{prefix}:{datetime.utcnow():%Y%m%d%H}"


async def _raw_budget(wanted: int) -> int:
    """Сколько строк из партии можно записать, не рискуя диском сервера.

    Два предела: число строк за текущий час (RAW_LOGS_MAX_PER_HOUR) и
    свободное место на диске (RAW_LOGS_MIN_FREE_DISK_GB — Postgres живёт на
    том же сервере, что панель и чужие проекты). Выше предела строки
    отбрасываются, но ответ ноде — 200: ошибка заставила бы её слать ту же
    партию снова, а лавина повторов и была причиной аварии 03.09.2026.
    """
    if wanted <= 0:
        return 0
    try:
        free_gb = shutil.disk_usage("/").free / 1024 ** 3
    except OSError:
        free_gb = None
    if free_gb is not None and free_gb < settings.RAW_LOGS_MIN_FREE_DISK_GB:
        logger.error(
            "Приём логов: на диске %.1f ГБ (порог %.1f) — партия отброшена",
            free_gb, settings.RAW_LOGS_MIN_FREE_DISK_GB,
        )
        return 0
    client = redis_client.redis
    if client is None:
        return wanted
    key = _hour_key("raw_rows")
    try:
        total = await client.incrby(key, wanted)
        await client.expire(key, 2 * 24 * 3600)
    except Exception as e:  # noqa: BLE001 — без Redis лимит не считаем, но пишем
        logger.warning("Приём логов: счётчик часа недоступен: %s", e)
        return wanted
    limit = settings.RAW_LOGS_MAX_PER_HOUR
    if total <= limit:
        return wanted
    allowed = max(0, wanted - (total - limit))
    if allowed < wanted:
        logger.warning(
            "Приём логов: за час уже %s строк (предел %s) — отброшено %s",
            total, limit, wanted - allowed,
        )
    return allowed


async def _mark_dirty_hours(rows: List[Dict[str, Any]]) -> None:
    """Запомнить часы, в которые легли строки, — их пересчитает свод.

    Нода, пока панель не отвечала, копит до 5000 строк и досылает их потом,
    в том числе за часы, которые почасовой свод давно закрыл. Без пометки
    такие строки есть в сырых логах, но не в сводах — и итоги экранов
    расходятся с топами (так было после включения приёма 23.09.2026).
    """
    client = redis_client.redis
    if client is None:
        return
    hours = {row["timestamp"].strftime("%Y-%m-%dT%H") for row in rows}
    try:
        await client.sadd(DIRTY_HOURS_KEY, *hours)
        await client.expire(DIRTY_HOURS_KEY, 7 * 24 * 3600)
    except Exception as e:  # noqa: BLE001 — свод всё равно пересчитает последние часы
        logger.debug("Приём логов: часы не помечены: %s", e)


async def _count(*, unmatched: int, dropped: int) -> None:
    """Счётчики отброшенного за час — чтобы тишина в аналитике была объяснима."""
    client = redis_client.redis
    if client is None or not (unmatched or dropped):
        return
    try:
        for name, value in (("unmatched", unmatched), ("dropped", dropped)):
            if value:
                key = _hour_key(name)
                await client.incrby(key, value)
                await client.expire(key, 7 * 24 * 3600)
    except Exception as e:  # noqa: BLE001
        logger.debug("Приём логов: счётчик не записан: %s", e)


@router.get("/acme-challenge/{token}", response_class=PlainTextResponse)
async def get_acme_challenge(
    token: str,
    node: EdgeNode = Depends(verify_edge_node),
):
    """Get ACME challenge response for edge nodes"""
    logger.info(f"ACME challenge request from edge node {node.name} for token: {token[:20]}...")

    validation = None
    if redis_client:
        key = f"acme:challenge:{token}"
        validation = await redis_client.get(key)
        logger.info(f"Redis lookup for key: {key}, found: {validation is not None}")

    if not validation:
        if redis_client and settings.DEBUG:
            try:
                all_keys = await redis_client.keys("acme:challenge:*")
                logger.warning(f"Challenge not found. Available keys: {all_keys}")
            except Exception as e:
                logger.warning(f"Could not list ACME keys: {e}")

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Challenge not found",
        )

    return PlainTextResponse(content=validation)


@router.get("/download/edge_config_updater.py", response_class=PlainTextResponse)
async def download_edge_config_updater(
    node: EdgeNode = Depends(verify_edge_node),
):
    """Download latest edge_config_updater.py for edge nodes"""
    from pathlib import Path

    logger.info(f"Edge node {node.name} requesting edge_config_updater.py download")

    updater_path = Path(__file__).parent.parent.parent / "edge_node" / "edge_config_updater.py"
    if not updater_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="edge_config_updater.py not found",
        )

    with open(updater_path, "r", encoding="utf-8") as f:
        content = f.read()

    logger.info(f"Sending edge_config_updater.py ({len(content)} bytes)")
    return PlainTextResponse(content=content)
