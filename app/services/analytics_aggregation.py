"""Analytics aggregation — hourly, daily, geo, top paths, error stats, and cleanup."""
import logging
from typing import Optional, Dict
from datetime import datetime, timedelta, date
from sqlalchemy import select, func, case, desc, delete
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


async def aggregate_hourly_stats(
    db: AsyncSession, target_hour: Optional[datetime] = None
) -> int:
    """Aggregate raw logs into hourly stats. Returns number of records processed."""
    if target_hour is None:
        now = datetime.utcnow()
        target_hour = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)

    hour_start = target_hour.replace(minute=0, second=0, microsecond=0)
    hour_end = hour_start + timedelta(hours=1)

    logger.info(f"Aggregating hourly stats for {hour_start} to {hour_end}")

    query = select(
        func.date_trunc("hour", RequestLog.timestamp).label("hour"),
        RequestLog.domain_id,
        RequestLog.edge_node_id,
        func.count(RequestLog.id).label("total_requests"),
        func.coalesce(func.sum(RequestLog.bytes_sent), 0).label("total_bytes_sent"),
        func.count(case((RequestLog.status_code.between(200, 299), 1))).label("status_2xx"),
        func.count(case((RequestLog.status_code.between(300, 399), 1))).label("status_3xx"),
        func.count(case((RequestLog.status_code.between(400, 499), 1))).label("status_4xx"),
        func.count(case((RequestLog.status_code.between(500, 599), 1))).label("status_5xx"),
        func.count(case((RequestLog.cache_status == "HIT", 1))).label("cache_hits"),
        func.count(case((RequestLog.cache_status == "MISS", 1))).label("cache_misses"),
        func.count(case((RequestLog.cache_status == "BYPASS", 1))).label("cache_bypass"),
        func.count(case((RequestLog.waf_status == "blocked", 1))).label("waf_blocked"),
        func.count(case((RequestLog.waf_status == "challenged", 1))).label("waf_challenged"),
        func.coalesce(func.avg(RequestLog.request_time), 0).label("avg_response_time"),
    ).where(
        RequestLog.timestamp >= hour_start, RequestLog.timestamp < hour_end
    ).group_by(
        func.date_trunc("hour", RequestLog.timestamp),
        RequestLog.domain_id,
        RequestLog.edge_node_id,
    )

    result = await db.execute(query)
    rows = result.all()

    records_processed = 0
    for row in rows:
        stmt = insert(HourlyStats).values(
            hour=row.hour,
            domain_id=row.domain_id,
            edge_node_id=row.edge_node_id,
            total_requests=row.total_requests,
            total_bytes_sent=row.total_bytes_sent,
            total_bytes_received=0,
            status_2xx=row.status_2xx,
            status_3xx=row.status_3xx,
            status_4xx=row.status_4xx,
            status_5xx=row.status_5xx,
            cache_hits=row.cache_hits,
            cache_misses=row.cache_misses,
            cache_bypass=row.cache_bypass,
            waf_blocked=row.waf_blocked,
            waf_challenged=row.waf_challenged,
            avg_response_time=float(row.avg_response_time or 0),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_hourly_stats",
            set_={
                "total_requests": stmt.excluded.total_requests,
                "total_bytes_sent": stmt.excluded.total_bytes_sent,
                "status_2xx": stmt.excluded.status_2xx,
                "status_3xx": stmt.excluded.status_3xx,
                "status_4xx": stmt.excluded.status_4xx,
                "status_5xx": stmt.excluded.status_5xx,
                "cache_hits": stmt.excluded.cache_hits,
                "cache_misses": stmt.excluded.cache_misses,
                "cache_bypass": stmt.excluded.cache_bypass,
                "waf_blocked": stmt.excluded.waf_blocked,
                "waf_challenged": stmt.excluded.waf_challenged,
                "avg_response_time": stmt.excluded.avg_response_time,
                "updated_at": datetime.utcnow(),
            },
        )
        await db.execute(stmt)
        records_processed += 1

    await db.commit()
    logger.info(f"Aggregated {records_processed} hourly stats records")
    return records_processed


async def aggregate_daily_stats(
    db: AsyncSession, target_date: Optional[date] = None
) -> int:
    """Aggregate hourly stats into daily stats."""
    if target_date is None:
        target_date = (datetime.utcnow() - timedelta(days=1)).date()

    logger.info(f"Aggregating daily stats for {target_date}")

    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)

    query = select(
        HourlyStats.domain_id,
        func.sum(HourlyStats.total_requests).label("total_requests"),
        func.sum(HourlyStats.total_bytes_sent).label("total_bytes_sent"),
        func.sum(HourlyStats.total_bytes_received).label("total_bytes_received"),
        func.sum(HourlyStats.status_2xx).label("status_2xx"),
        func.sum(HourlyStats.status_3xx).label("status_3xx"),
        func.sum(HourlyStats.status_4xx).label("status_4xx"),
        func.sum(HourlyStats.status_5xx).label("status_5xx"),
        func.sum(HourlyStats.cache_hits).label("cache_hits"),
        func.sum(HourlyStats.cache_misses).label("cache_misses"),
        func.sum(HourlyStats.cache_bypass).label("cache_bypass"),
        func.sum(HourlyStats.waf_blocked).label("waf_blocked"),
        func.sum(HourlyStats.waf_challenged).label("waf_challenged"),
        func.avg(HourlyStats.avg_response_time).label("avg_response_time"),
        func.max(HourlyStats.total_requests).label("peak_requests_hour"),
        func.max(HourlyStats.total_bytes_sent).label("peak_bandwidth_hour"),
    ).where(
        HourlyStats.hour >= day_start, HourlyStats.hour < day_end
    ).group_by(HourlyStats.domain_id)

    result = await db.execute(query)
    rows = result.all()

    records_processed = 0
    for row in rows:
        uv_query = select(
            func.count(func.distinct(RequestLog.client_ip))
        ).where(
            RequestLog.domain_id == row.domain_id,
            RequestLog.timestamp >= day_start,
            RequestLog.timestamp < day_end,
        )
        unique_visitors = (await db.execute(uv_query)).scalar() or 0

        stmt = insert(DailyStats).values(
            day=target_date,
            domain_id=row.domain_id,
            total_requests=row.total_requests or 0,
            total_bytes_sent=row.total_bytes_sent or 0,
            total_bytes_received=row.total_bytes_received or 0,
            status_2xx=row.status_2xx or 0,
            status_3xx=row.status_3xx or 0,
            status_4xx=row.status_4xx or 0,
            status_5xx=row.status_5xx or 0,
            cache_hits=row.cache_hits or 0,
            cache_misses=row.cache_misses or 0,
            cache_bypass=row.cache_bypass or 0,
            waf_blocked=row.waf_blocked or 0,
            waf_challenged=row.waf_challenged or 0,
            avg_response_time=float(row.avg_response_time or 0),
            peak_requests_hour=row.peak_requests_hour or 0,
            peak_bandwidth_hour=row.peak_bandwidth_hour or 0,
            unique_visitors=unique_visitors,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_daily_stats",
            set_={
                "total_requests": stmt.excluded.total_requests,
                "total_bytes_sent": stmt.excluded.total_bytes_sent,
                "total_bytes_received": stmt.excluded.total_bytes_received,
                "status_2xx": stmt.excluded.status_2xx,
                "status_3xx": stmt.excluded.status_3xx,
                "status_4xx": stmt.excluded.status_4xx,
                "status_5xx": stmt.excluded.status_5xx,
                "cache_hits": stmt.excluded.cache_hits,
                "cache_misses": stmt.excluded.cache_misses,
                "cache_bypass": stmt.excluded.cache_bypass,
                "waf_blocked": stmt.excluded.waf_blocked,
                "waf_challenged": stmt.excluded.waf_challenged,
                "avg_response_time": stmt.excluded.avg_response_time,
                "peak_requests_hour": stmt.excluded.peak_requests_hour,
                "peak_bandwidth_hour": stmt.excluded.peak_bandwidth_hour,
                "unique_visitors": stmt.excluded.unique_visitors,
                "updated_at": datetime.utcnow(),
            },
        )
        await db.execute(stmt)
        records_processed += 1

    await db.commit()
    logger.info(f"Aggregated {records_processed} daily stats records")
    return records_processed


async def aggregate_geo_stats(
    db: AsyncSession, target_date: Optional[date] = None
) -> int:
    """Aggregate geographic stats for a specific day."""
    if target_date is None:
        target_date = (datetime.utcnow() - timedelta(days=1)).date()

    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)

    logger.info(f"Aggregating geo stats for {target_date}")

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
    ).group_by(RequestLog.domain_id, RequestLog.country_code)

    result = await db.execute(query)
    rows = result.all()

    records_processed = 0
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
        records_processed += 1

    await db.commit()
    logger.info(f"Aggregated {records_processed} geo stats records")
    return records_processed


async def aggregate_top_paths(
    db: AsyncSession, target_date: Optional[date] = None, limit: int = 100
) -> int:
    """Aggregate top paths for a specific day."""
    if target_date is None:
        target_date = (datetime.utcnow() - timedelta(days=1)).date()

    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)

    logger.info(f"Aggregating top paths for {target_date}")

    domains_result = await db.execute(select(Domain.id))
    domain_ids = [d[0] for d in domains_result.all()]

    records_processed = 0
    for domain_id in domain_ids:
        query = select(
            RequestLog.path,
            func.count(RequestLog.id).label("total_requests"),
            func.coalesce(func.sum(RequestLog.bytes_sent), 0).label("total_bytes_sent"),
            func.count(case((RequestLog.cache_status == "HIT", 1))).label("cache_hits"),
            func.count(case((RequestLog.cache_status == "MISS", 1))).label("cache_misses"),
            func.count(case((RequestLog.status_code.between(200, 299), 1))).label("status_2xx"),
            func.count(case((RequestLog.status_code.between(400, 499), 1))).label("status_4xx"),
            func.count(case((RequestLog.status_code.between(500, 599), 1))).label("status_5xx"),
        ).where(
            RequestLog.domain_id == domain_id,
            RequestLog.timestamp >= day_start,
            RequestLog.timestamp < day_end,
        ).group_by(RequestLog.path).order_by(desc("total_requests")).limit(limit)

        result = await db.execute(query)
        for row in result.all():
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
            records_processed += 1

    await db.commit()
    logger.info(f"Aggregated {records_processed} top paths records")
    return records_processed


async def aggregate_error_stats(
    db: AsyncSession, target_date: Optional[date] = None, limit: int = 50
) -> int:
    """Aggregate error stats for a specific day."""
    if target_date is None:
        target_date = (datetime.utcnow() - timedelta(days=1)).date()

    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)

    logger.info(f"Aggregating error stats for {target_date}")

    query = select(
        RequestLog.domain_id,
        RequestLog.status_code,
        RequestLog.path,
        func.count(RequestLog.id).label("error_count"),
    ).where(
        RequestLog.timestamp >= day_start,
        RequestLog.timestamp < day_end,
        RequestLog.status_code >= 400,
    ).group_by(
        RequestLog.domain_id, RequestLog.status_code, RequestLog.path
    ).order_by(desc("error_count")).limit(limit * 10)

    result = await db.execute(query)
    rows = result.all()

    records_processed = 0
    for row in rows:
        if row.domain_id is None:
            continue
        stmt = insert(ErrorStats).values(
            day=target_date,
            domain_id=row.domain_id,
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
        records_processed += 1

    await db.commit()
    logger.info(f"Aggregated {records_processed} error stats records")
    return records_processed


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
