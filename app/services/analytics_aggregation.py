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
from sqlalchemy import select, func, case, desc, delete, and_, literal_column
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


def raw_metrics():
    """Метрики сводов, посчитанные по сырым логам (для часа и для «сейчас»)."""
    return (
        func.count(RequestLog.id).label("total_requests"),
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
    )


_HOURLY_FIELDS = (
    "total_requests", "total_bytes_sent", "status_2xx", "status_3xx",
    "status_4xx", "status_5xx", "cache_hits", "cache_misses", "cache_bypass",
    "cached_bytes", "waf_blocked", "waf_challenged", "rate_limited",
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
        stmt = insert(HourlyStats).values(
            hour=hour_start,
            domain_id=row.domain_id,
            edge_node_id=row.edge_node_id,
            total_bytes_received=0,
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


async def aggregate_recent_hours(db: AsyncSession, hours: int = RECENT_HOURS) -> int:
    """Пересчитать текущий и несколько прошедших часов (идемпотентно)."""
    current = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    total = 0
    for back in range(hours, -1, -1):
        total += await aggregate_hourly_stats(db, current - timedelta(hours=back))
    return total


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
    ).where(
        HourlyStats.hour >= day_start,
        HourlyStats.hour < day_end,
        HourlyStats.domain_id.isnot(None),
    ).group_by(HourlyStats.domain_id, HourlyStats.hour).subquery()

    query = select(
        per_hour.c.domain_id,
        *[func.sum(per_hour.c[f]).label(f) for f in _HOURLY_FIELDS],
        func.sum(per_hour.c.rt_weighted).label("rt_weighted"),
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
        values.update(
            avg_response_time=avg_rt,
            peak_requests_hour=int(row.peak_requests_hour or 0),
            peak_bandwidth_hour=int(row.peak_bandwidth_hour or 0),
            unique_visitors=int(unique_visitors),
        )
        stmt = insert(DailyStats).values(
            day=target_date,
            domain_id=row.domain_id,
            total_bytes_received=0,
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
