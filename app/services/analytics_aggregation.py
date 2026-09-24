"""Своды аналитики: сырые логи → часы → сутки, плюс суточные топы и уборка.

Как устроено (с 23.09.2026):

* почасовой свод пересчитывается каждые 5 минут за последние часы
  (``aggregate_recent_hours``). Вставка — upsert, поэтому пересчёт
  безвреден, а логи, которые нода досылает с опозданием (она копит их, пока
  панель недоступна), попадают в свой час, а не теряются;
* суточный свод собирается из почасового; уникальные посетители — из сырых
  логов (их нельзя сложить из часов);
* запросы экранов (``analytics_query``) берут часы для прошедших часов и сырые
  логи для текущего — отставания в час больше нет.
"""
import logging
from typing import Optional, Dict, List
from datetime import datetime, timedelta, date
from sqlalchemy import select, func, case, desc, delete, and_, or_, literal_column, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.log import RequestLog
from app.models.analytics import (
    HourlyStats, DailyStats, GeoStats, TopPathsStats, ErrorStats
)
from app.models.domain import Domain
from app.core.config import settings

logger = logging.getLogger(__name__)

RAW_LOGS_RETENTION_DAYS = getattr(settings, "ANALYTICS_RAW_LOGS_RETENTION", 30)
HOURLY_STATS_RETENTION_DAYS = getattr(settings, "ANALYTICS_HOURLY_RETENTION", 90)
DAILY_STATS_RETENTION_DAYS = getattr(settings, "ANALYTICS_DAILY_RETENTION", 365)

# Сколько последних часов пересчитывать на каждом запуске: нода держит до
# 5000 неотправленных строк и досылает их, когда панель снова отвечает.
RECENT_HOURS = 3

# $upstream_cache_status у nginx: отдано из кэша — HIT, а ещё STALE, UPDATING
# и REVALIDATED (копия из кэша, пусть и устаревшая или перепроверенная). За
# origin ходили — MISS и EXPIRED. BYPASS — кэш пропущен правилом. Пусто —
# запрос вообще не кэшируемый. Раньше считались только HIT/MISS/BYPASS, и
# STALE/EXPIRED выпадали из доли кэша.
CACHE_HIT_STATUSES = ("HIT", "STALE", "UPDATING", "REVALIDATED")
CACHE_MISS_STATUSES = ("MISS", "EXPIRED")
CACHE_BYPASS_STATUSES = ("BYPASS",)


def cache_hit_expr():
    return RequestLog.cache_status.in_(CACHE_HIT_STATUSES)


def cache_miss_expr():
    return RequestLog.cache_status.in_(CACHE_MISS_STATUSES)


def cache_bypass_expr():
    return RequestLog.cache_status.in_(CACHE_BYPASS_STATUSES)


def page_view_expr():
    """Просмотр страницы: GET страницы, а не файла, с ответом 2xx или 304.

    Страница — путь без расширения или .html; /api/ — не страницы, а вызовы
    приложений. 304 — страница из кэша браузера при повторном заходе: это
    тоже просмотр. Регулярки — литералами: asyncpg передал бы строки
    параметрами (см. ловушку GROUP BY в analytics_query).
    """
    path = RequestLog.path
    return and_(
        RequestLog.method == "GET",
        or_(RequestLog.status_code.between(200, 299), RequestLog.status_code == 304),
        or_(
            ~path.op("~")(literal_column(r"'\.[A-Za-z0-9]{1,12}$'")),
            path.op("~*")(literal_column(r"'\.html?$'")),
        ),
        ~path.like(literal_column("'/api/%'")),
    )


def raw_metrics():
    """Метрики сводов, посчитанные по сырым логам (для часа и для «сейчас»)."""
    return (
        func.count(RequestLog.id).label("total_requests"),
        func.count(case((page_view_expr(), 1))).label("page_views"),
        func.coalesce(func.sum(RequestLog.bytes_sent), 0).label("total_bytes_sent"),
        func.count(case((RequestLog.status_code.between(200, 299), 1))).label("status_2xx"),
        func.count(case((RequestLog.status_code.between(300, 399), 1))).label("status_3xx"),
        func.count(case((RequestLog.status_code.between(400, 499), 1))).label("status_4xx"),
        func.count(case((RequestLog.status_code.between(500, 599), 1))).label("status_5xx"),
        func.count(case((cache_hit_expr(), 1))).label("cache_hits"),
        func.count(case((cache_miss_expr(), 1))).label("cache_misses"),
        func.count(case((cache_bypass_expr(), 1))).label("cache_bypass"),
        func.coalesce(
            func.sum(case((cache_hit_expr(), RequestLog.bytes_sent), else_=0)), 0
        ).label("cached_bytes"),
        func.count(case((RequestLog.waf_status == "blocked", 1))).label("waf_blocked"),
        func.count(case((RequestLog.waf_status == "challenged", 1))).label("waf_challenged"),
        func.count(case((RequestLog.status_code == 429, 1))).label("rate_limited"),
        func.coalesce(func.avg(RequestLog.request_time), 0).label("avg_response_time"),
        func.coalesce(func.sum(RequestLog.bytes_received), 0).label("total_bytes_received"),
        func.count(RequestLog.upstream_time).label("origin_requests"),
        func.coalesce(func.avg(RequestLog.upstream_time), 0).label("avg_origin_time"),
    )


_HOURLY_FIELDS = (
    "total_requests", "page_views", "total_bytes_sent", "status_2xx", "status_3xx",
    "status_4xx", "status_5xx", "cache_hits", "cache_misses", "cache_bypass",
    "cached_bytes", "waf_blocked", "waf_challenged", "rate_limited",
    "total_bytes_received", "origin_requests",
)


async def aggregate_hourly_stats(
    db: AsyncSession, target_hour: Optional[datetime] = None
) -> int:
    """Свод одного часа по доменам и нодам. Возвращает число строк свода."""
    if target_hour is None:
        now = datetime.utcnow()
        target_hour = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)

    hour_start = target_hour.replace(minute=0, second=0, microsecond=0)
    hour_end = hour_start + timedelta(hours=1)

    # Час один — он задан условием WHERE, группировать по date_trunc не нужно.
    # До 23.09.2026 группировали, и asyncpg передавал 'hour' в SELECT и в
    # GROUP BY двумя разными параметрами: Postgres не считал выражения
    # одинаковыми и падал с GroupingError. Почасовой свод не записал ни строки.
    query = select(
        RequestLog.domain_id,
        RequestLog.edge_node_id,
        *raw_metrics(),
    ).where(
        RequestLog.timestamp >= hour_start,
        RequestLog.timestamp < hour_end,
        RequestLog.domain_id.isnot(None),
    ).group_by(RequestLog.domain_id, RequestLog.edge_node_id)

    rows = (await db.execute(query)).all()

    now = datetime.utcnow()
    for row in rows:
        values = {name: int(getattr(row, name) or 0) for name in _HOURLY_FIELDS}
        values["avg_response_time"] = float(row.avg_response_time or 0)
        values["avg_origin_time"] = float(row.avg_origin_time or 0)
        stmt = insert(HourlyStats).values(
            hour=hour_start,
            domain_id=row.domain_id,
            edge_node_id=row.edge_node_id,
            created_at=now,
            updated_at=now,
            **values,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_hourly_stats",
            set_={**{k: stmt.excluded[k] for k in values}, "updated_at": now},
        )
        await db.execute(stmt)

    await db.commit()
    logger.info("Hourly stats %s: %s rows", hour_start, len(rows))
    return len(rows)


# Часы, в которые приём логов положил строки (app/api/internal_logs.py).
DIRTY_HOURS_KEY = "analytics:dirty_hours"
_HOUR_FMT = "%Y-%m-%dT%H"


async def _redis():
    import redis.asyncio as aioredis

    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


async def _close(client) -> None:
    closer = getattr(client, "aclose", None) or client.close
    await closer()


async def pop_dirty_hours(limit: int = 5000) -> List[datetime]:
    """Забрать помеченные часы (SPOP — атомарно, двум воркерам не достанется одно)."""
    client = await _redis()
    try:
        values = await client.spop(DIRTY_HOURS_KEY, limit) or []
    finally:
        await _close(client)
    hours = []
    for value in values:
        try:
            hours.append(datetime.strptime(value, _HOUR_FMT))
        except ValueError:
            continue
    return hours


async def _return_dirty_hours(hours: List[datetime]) -> None:
    if not hours:
        return
    client = await _redis()
    try:
        await client.sadd(DIRTY_HOURS_KEY, *[h.strftime(_HOUR_FMT) for h in hours])
    finally:
        await _close(client)


# Страница, а не файл: без расширения или .html. Ассеты — то, что грузит
# только настоящий браузер.
_PAGE_SQL = (
    "method = 'GET' AND status_code < 400 "
    r"AND (path !~ '\.[A-Za-z0-9]{1,12}$' OR path ~* '\.html?$')"
)
_VPN_SQL = f"""
WITH s AS (
    SELECT domain_id, client_ip, coalesce(user_agent, '') AS ua,
           count(DISTINCT path) FILTER (WHERE {_PAGE_SQL}) AS pages,
           count(*) FILTER (WHERE path ~* '\\.(css|js|mjs)$') AS assets,
           extract(epoch FROM max(timestamp) FILTER (WHERE {_PAGE_SQL})
                            - min(timestamp) FILTER (WHERE {_PAGE_SQL})) AS span
    FROM request_logs
    WHERE timestamp >= :start AND timestamp < :end AND client_class = 'hosted'
    GROUP BY 1, 2, 3
), people AS (
    SELECT domain_id, client_ip, ua FROM s
    WHERE pages >= 2 AND (
        (assets >= 3 AND span >= 20 AND pages <= 12 * greatest(span / 60.0, 1))
        OR (span >= 120 AND pages <= 2 * greatest(span / 60.0, 1))
    )
)
UPDATE request_logs r SET client_class = 'vpn'
FROM people p
WHERE r.timestamp >= :start AND r.timestamp < :end AND r.client_class = 'hosted'
  AND r.domain_id = p.domain_id AND r.client_ip = p.client_ip
  AND coalesce(r.user_agent, '') = p.ua
"""


async def refine_traffic_classes(db: AsyncSession, start: datetime, end: datetime) -> Dict[str, int]:
    """Досказать классы трафика, которые видны только по нескольким запросам.

    При приёме строка классифицируется одна (``traffic_class.classify``).
    Здесь — по всем запросам адреса за период:

    * адрес из сети хостинга, который хоть раз искал ``/.env`` или
      ``wp-login.php``, — сканер во всех своих запросах. Домашние и
      мобильные адреса не трогаем: за одним IP оператора сидят тысячи людей,
      сканером считается только сам запрос-проба;
    * браузер из дата-центра, который листает страницы как человек (две и
      больше, с паузами, с загрузкой CSS и JS, не десятки в минуту), — это
      человек через VPN. Так ходят многие посетители из России. Боты под
      браузером открывают одну страницу или обходят сайт пачкой за секунды.
      Пороги подобраны на логах всех доменов за 1–24.09.2026.
    """
    from app.services import ip_networks, traffic_class as tc

    scanners = (await db.execute(
        select(RequestLog.client_ip).where(
            RequestLog.timestamp >= start, RequestLog.timestamp < end,
            RequestLog.client_class == tc.SCANNER,
        ).distinct()
    )).scalars().all()
    hosted = [ip for ip in scanners if ip_networks.is_hosting(*ip_networks.lookup(ip))]
    flagged = 0
    if hosted:
        result = await db.execute(
            RequestLog.__table__.update()
            .where(
                RequestLog.timestamp >= start, RequestLog.timestamp < end,
                RequestLog.client_ip.in_(hosted),
                RequestLog.client_class.in_((tc.HUMAN, tc.VPN, tc.HOSTED, tc.BOT)),
            )
            .values(client_class=tc.SCANNER)
        )
        flagged = result.rowcount or 0
    result = await db.execute(text(_VPN_SQL), {"start": start, "end": end})
    promoted = result.rowcount or 0
    await db.commit()
    return {"scanner_rows": flagged, "vpn_rows": promoted}


async def aggregate_recent_hours(db: AsyncSession, hours: int = RECENT_HOURS) -> Dict[str, int]:
    """Пересчитать последние часы и все часы, куда дошли опоздавшие логи.

    Идемпотентно (upsert). Если в опоздавших часах есть прошедшие сутки, их
    суточные своды тоже пересчитываются — иначе «30 дней» и «6 месяцев»
    расходились бы с «24 часами».
    """
    current = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    targets = {current - timedelta(hours=back) for back in range(hours + 1)}
    dirty = await pop_dirty_hours()
    targets |= set(dirty)
    try:
        # Классы трафика — не повод остановить свод: ошибка пересмотра только в лог.
        try:
            await refine_traffic_classes(db, min(targets), datetime.utcnow())
        except Exception:
            logger.exception("Классы трафика не пересмотрены")
            await db.rollback()
        rows = 0
        for hour in sorted(targets):
            rows += await aggregate_hourly_stats(db, hour)
        today = datetime.utcnow().date()
        days = sorted({h.date() for h in dirty if h.date() < today})
        for day in days:
            await aggregate_day(db, day)
    except Exception:
        # Не потерять пометки: следующий запуск через 5 минут повторит.
        await _return_dirty_hours(dirty)
        raise
    return {"hours": len(targets), "late_hours": len(dirty), "days": len(days), "rows": rows}


async def aggregate_daily_stats(
    db: AsyncSession, target_date: Optional[date] = None
) -> int:
    """Свод суток по доменам из почасового свода."""
    if target_date is None:
        target_date = (datetime.utcnow() - timedelta(days=1)).date()

    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)

    # Сначала час по домену целиком (сумма по нодам) — пик суток считается по
    # нему. Раньше максимум брали по строкам «час × нода», и пик занижался
    # во столько раз, сколько нод делили трафик.
    per_hour = select(
        HourlyStats.domain_id.label("domain_id"),
        HourlyStats.hour.label("hour"),
        *[func.sum(getattr(HourlyStats, f)).label(f) for f in _HOURLY_FIELDS],
        func.sum(HourlyStats.avg_response_time * HourlyStats.total_requests).label("rt_weighted"),
        func.sum(HourlyStats.avg_origin_time * HourlyStats.origin_requests).label("ot_weighted"),
    ).where(
        HourlyStats.hour >= day_start,
        HourlyStats.hour < day_end,
        HourlyStats.domain_id.isnot(None),
    ).group_by(HourlyStats.domain_id, HourlyStats.hour).subquery()

    query = select(
        per_hour.c.domain_id,
        *[func.sum(per_hour.c[f]).label(f) for f in _HOURLY_FIELDS],
        func.sum(per_hour.c.rt_weighted).label("rt_weighted"),
        func.sum(per_hour.c.ot_weighted).label("ot_weighted"),
        func.max(per_hour.c.total_requests).label("peak_requests_hour"),
        func.max(per_hour.c.total_bytes_sent).label("peak_bandwidth_hour"),
    ).group_by(per_hour.c.domain_id)

    rows = (await db.execute(query)).all()

    now = datetime.utcnow()
    for row in rows:
        unique_visitors = (await db.execute(
            select(func.count(func.distinct(RequestLog.client_ip))).where(
                RequestLog.domain_id == row.domain_id,
                RequestLog.timestamp >= day_start,
                RequestLog.timestamp < day_end,
            )
        )).scalar() or 0
        requests = int(row.total_requests or 0)
        # Среднее время ответа — взвешенное по запросам, а не среднее средних:
        # тихий час с одним медленным запросом не должен весить как пиковый.
        avg_rt = float(row.rt_weighted or 0) / requests if requests else 0.0
        values = {name: int(getattr(row, name) or 0) for name in _HOURLY_FIELDS}
        origin = int(row.origin_requests or 0)
        values.update(
            avg_response_time=avg_rt,
            avg_origin_time=float(row.ot_weighted or 0) / origin if origin else 0.0,
            peak_requests_hour=int(row.peak_requests_hour or 0),
            peak_bandwidth_hour=int(row.peak_bandwidth_hour or 0),
            unique_visitors=int(unique_visitors),
        )
        stmt = insert(DailyStats).values(
            day=target_date,
            domain_id=row.domain_id,
            created_at=now,
            updated_at=now,
            **values,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_daily_stats",
            set_={**{k: stmt.excluded[k] for k in values}, "updated_at": now},
        )
        await db.execute(stmt)

    await db.commit()
    logger.info("Daily stats %s: %s rows", target_date, len(rows))
    return len(rows)


async def aggregate_geo_stats(
    db: AsyncSession, target_date: Optional[date] = None
) -> int:
    """Страны за сутки по доменам."""
    if target_date is None:
        target_date = (datetime.utcnow() - timedelta(days=1)).date()

    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)

    query = select(
        RequestLog.domain_id,
        RequestLog.country_code,
        func.count(RequestLog.id).label("total_requests"),
        func.coalesce(func.sum(RequestLog.bytes_sent), 0).label("total_bytes_sent"),
        func.count(func.distinct(RequestLog.client_ip)).label("unique_visitors"),
    ).where(
        RequestLog.timestamp >= day_start,
        RequestLog.timestamp < day_end,
        RequestLog.country_code.isnot(None),
        # Строка без домена в уникальном ключе не конфликтует — upsert
        # плодил бы дубли при каждом пересчёте.
        RequestLog.domain_id.isnot(None),
    ).group_by(RequestLog.domain_id, RequestLog.country_code)

    rows = (await db.execute(query)).all()
    for row in rows:
        stmt = insert(GeoStats).values(
            day=target_date,
            domain_id=row.domain_id,
            country_code=row.country_code,
            total_requests=row.total_requests,
            total_bytes_sent=row.total_bytes_sent,
            unique_visitors=row.unique_visitors,
            created_at=datetime.utcnow(),
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_geo_stats",
            set_={
                "total_requests": stmt.excluded.total_requests,
                "total_bytes_sent": stmt.excluded.total_bytes_sent,
                "unique_visitors": stmt.excluded.unique_visitors,
            },
        )
        await db.execute(stmt)

    await db.commit()
    logger.info("Geo stats %s: %s rows", target_date, len(rows))
    return len(rows)


async def _domain_ids(db: AsyncSession) -> List[int]:
    return [d[0] for d in (await db.execute(select(Domain.id))).all()]


async def aggregate_top_paths(
    db: AsyncSession, target_date: Optional[date] = None, limit: int = 100
) -> int:
    """Топ страниц за сутки по каждому домену."""
    if target_date is None:
        target_date = (datetime.utcnow() - timedelta(days=1)).date()

    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)

    records = 0
    for domain_id in await _domain_ids(db):
        query = select(
            RequestLog.path,
            func.count(RequestLog.id).label("total_requests"),
            func.coalesce(func.sum(RequestLog.bytes_sent), 0).label("total_bytes_sent"),
            func.count(case((cache_hit_expr(), 1))).label("cache_hits"),
            func.count(case((cache_miss_expr(), 1))).label("cache_misses"),
            func.count(case((RequestLog.status_code.between(200, 299), 1))).label("status_2xx"),
            func.count(case((RequestLog.status_code.between(400, 499), 1))).label("status_4xx"),
            func.count(case((RequestLog.status_code.between(500, 599), 1))).label("status_5xx"),
        ).where(
            RequestLog.domain_id == domain_id,
            RequestLog.timestamp >= day_start,
            RequestLog.timestamp < day_end,
        ).group_by(RequestLog.path).order_by(desc("total_requests")).limit(limit)

        for row in (await db.execute(query)).all():
            stmt = insert(TopPathsStats).values(
                day=target_date,
                domain_id=domain_id,
                path=row.path[:2048] if row.path else "/",
                total_requests=row.total_requests,
                total_bytes_sent=row.total_bytes_sent,
                cache_hits=row.cache_hits,
                cache_misses=row.cache_misses,
                status_2xx=row.status_2xx,
                status_4xx=row.status_4xx,
                status_5xx=row.status_5xx,
                created_at=datetime.utcnow(),
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_top_paths",
                set_={
                    "total_requests": stmt.excluded.total_requests,
                    "total_bytes_sent": stmt.excluded.total_bytes_sent,
                    "cache_hits": stmt.excluded.cache_hits,
                    "cache_misses": stmt.excluded.cache_misses,
                    "status_2xx": stmt.excluded.status_2xx,
                    "status_4xx": stmt.excluded.status_4xx,
                    "status_5xx": stmt.excluded.status_5xx,
                },
            )
            await db.execute(stmt)
            records += 1

    await db.commit()
    logger.info("Top paths %s: %s rows", target_date, records)
    return records


async def aggregate_error_stats(
    db: AsyncSession, target_date: Optional[date] = None, limit: int = 50
) -> int:
    """Топ ошибок (4xx/5xx) за сутки — по каждому домену свой.

    Раньше лимит был общим на все домены, и шумный домен со сканерами
    вытеснял ошибки остальных целиком.
    """
    if target_date is None:
        target_date = (datetime.utcnow() - timedelta(days=1)).date()

    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)

    records = 0
    for domain_id in await _domain_ids(db):
        query = select(
            RequestLog.status_code,
            RequestLog.path,
            func.count(RequestLog.id).label("error_count"),
        ).where(
            RequestLog.domain_id == domain_id,
            RequestLog.timestamp >= day_start,
            RequestLog.timestamp < day_end,
            RequestLog.status_code >= 400,
        ).group_by(
            RequestLog.status_code, RequestLog.path
        ).order_by(desc("error_count")).limit(limit)

        for row in (await db.execute(query)).all():
            stmt = insert(ErrorStats).values(
                day=target_date,
                domain_id=domain_id,
                status_code=row.status_code,
                path=row.path[:2048] if row.path else "/",
                error_count=row.error_count,
                created_at=datetime.utcnow(),
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_error_stats",
                set_={"error_count": stmt.excluded.error_count},
            )
            await db.execute(stmt)
            records += 1

    await db.commit()
    logger.info("Error stats %s: %s rows", target_date, records)
    return records


async def aggregate_day(db: AsyncSession, target_date: date) -> Dict[str, int]:
    """Все суточные своды одного дня (после того как его часы посчитаны)."""
    return {
        "daily": await aggregate_daily_stats(db, target_date),
        "geo": await aggregate_geo_stats(db, target_date),
        "top_paths": await aggregate_top_paths(db, target_date),
        "errors": await aggregate_error_stats(db, target_date),
    }


async def backfill(db: AsyncSession, since: Optional[datetime] = None) -> Dict[str, int]:
    """Пересчитать своды по всем сырым логам с ``since`` (по умолчанию — все).

    Считаем только часы, в которых есть логи: пустые часы свода не нужны, а
    обход месяца по часам вслепую — 720 пустых запросов.
    """
    where = [RequestLog.domain_id.isnot(None)]
    if since is not None:
        where.append(RequestLog.timestamp >= since)
    hour_expr = func.date_trunc("hour", RequestLog.timestamp).label("h")
    # GROUP BY по номеру колонки: так Postgres не сравнивает два разных
    # параметра date_trunc (та же ловушка, что сломала почасовой свод).
    hours = [
        r.h for r in (await db.execute(
            select(hour_expr).where(and_(*where))
            .group_by(literal_column("1")).order_by(literal_column("1"))
        )).all()
    ]
    for hour in hours:
        await aggregate_hourly_stats(db, hour)
    days = sorted({h.date() for h in hours})
    today = datetime.utcnow().date()
    for day in days:
        if day < today:
            await aggregate_day(db, day)
    logger.info("Backfill: %s hours, %s days", len(hours), len(days))
    return {"hours": len(hours), "days": len([d for d in days if d < today])}


async def cleanup_old_data(db: AsyncSession) -> Dict[str, int]:
    """Clean up old data based on retention policies."""
    now = datetime.utcnow()
    deleted = {}

    raw_cutoff = now - timedelta(days=RAW_LOGS_RETENTION_DAYS)
    result = await db.execute(delete(RequestLog).where(RequestLog.timestamp < raw_cutoff))
    deleted["request_logs"] = result.rowcount
    logger.info(f"Deleted {deleted['request_logs']} old request logs (before {raw_cutoff})")

    hourly_cutoff = now - timedelta(days=HOURLY_STATS_RETENTION_DAYS)
    result = await db.execute(delete(HourlyStats).where(HourlyStats.hour < hourly_cutoff))
    deleted["hourly_stats"] = result.rowcount

    daily_cutoff = (now - timedelta(days=DAILY_STATS_RETENTION_DAYS)).date()
    result = await db.execute(delete(DailyStats).where(DailyStats.day < daily_cutoff))
    deleted["daily_stats"] = result.rowcount

    result = await db.execute(delete(GeoStats).where(GeoStats.day < daily_cutoff))
    deleted["geo_stats"] = result.rowcount

    result = await db.execute(delete(TopPathsStats).where(TopPathsStats.day < daily_cutoff))
    deleted["top_paths_stats"] = result.rowcount

    result = await db.execute(delete(ErrorStats).where(ErrorStats.day < daily_cutoff))
    deleted["error_stats"] = result.rowcount

    await db.commit()
    logger.info(f"Cleanup completed: {deleted}")
    return deleted
