"""Analytics service — query methods and backward-compatible aggregation delegates."""
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, date
from sqlalchemy import select, func, case, union_all, literal_column
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.log import RequestLog
from app.models.analytics import HourlyStats, DailyStats
from app.models.domain import Domain
from app.core.config import settings

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Service for analytics operations"""

    RAW_LOGS_RETENTION_DAYS = getattr(settings, "ANALYTICS_RAW_LOGS_RETENTION", 30)
    HOURLY_STATS_RETENTION_DAYS = getattr(settings, "ANALYTICS_HOURLY_RETENTION", 90)
    DAILY_STATS_RETENTION_DAYS = getattr(settings, "ANALYTICS_DAILY_RETENTION", 365)

    @staticmethod
    def get_time_range_start(range_str: str) -> datetime:
        """Get start time for a given time range string"""
        now = datetime.utcnow()
        mapping = {
            "1h": timedelta(hours=1),
            "24h": timedelta(days=1),
            "7d": timedelta(days=7),
            "30d": timedelta(days=30),
            "90d": timedelta(days=90),
            "6m": timedelta(days=180),
        }
        return now - mapping.get(range_str, timedelta(days=1))

    # ── Aggregation delegates (backward compat) ──────────────────────

    @staticmethod
    async def aggregate_hourly_stats(db, target_hour=None):
        from app.services.analytics_aggregation import aggregate_hourly_stats
        return await aggregate_hourly_stats(db, target_hour)

    @staticmethod
    async def aggregate_daily_stats(db, target_date=None):
        from app.services.analytics_aggregation import aggregate_daily_stats
        return await aggregate_daily_stats(db, target_date)

    @staticmethod
    async def aggregate_geo_stats(db, target_date=None):
        from app.services.analytics_aggregation import aggregate_geo_stats
        return await aggregate_geo_stats(db, target_date)

    @staticmethod
    async def aggregate_top_paths(db, target_date=None, limit=100):
        from app.services.analytics_aggregation import aggregate_top_paths
        return await aggregate_top_paths(db, target_date, limit)

    @staticmethod
    async def aggregate_error_stats(db, target_date=None, limit=50):
        from app.services.analytics_aggregation import aggregate_error_stats
        return await aggregate_error_stats(db, target_date, limit)

    @staticmethod
    async def cleanup_old_data(db):
        from app.services.analytics_aggregation import cleanup_old_data
        return await cleanup_old_data(db)

    # ── Query methods ────────────────────────────────────────────────

    @staticmethod
    async def get_global_stats_optimized(
        db: AsyncSession,
        range_str: str = "24h"
    ) -> Dict[str, Any]:
        """Get global statistics using aggregated data when possible."""
        start_time = AnalyticsService.get_time_range_start(range_str)

        if range_str in ["7d", "30d", "90d", "6m"]:
            start_date = start_time.date()
            query = select(
                func.sum(DailyStats.total_requests).label("total_requests"),
                func.sum(DailyStats.total_bytes_sent).label("total_bandwidth"),
                func.sum(DailyStats.waf_blocked).label("threats_blocked"),
                func.sum(DailyStats.status_2xx).label("status_2xx"),
                func.sum(DailyStats.status_3xx).label("status_3xx"),
                func.sum(DailyStats.status_4xx).label("status_4xx"),
                func.sum(DailyStats.status_5xx).label("status_5xx"),
                func.sum(DailyStats.cache_hits).label("cache_hits"),
            ).where(DailyStats.day >= start_date)
            result = await db.execute(query)
            stats = result.one()
        elif range_str == "24h":
            current_hour_start = datetime.utcnow().replace(minute=0, second=0, microsecond=0)

            hourly_q = select(
                func.coalesce(func.sum(HourlyStats.total_requests), 0).label("total_requests"),
                func.coalesce(func.sum(HourlyStats.total_bytes_sent), 0).label("total_bandwidth"),
                func.coalesce(func.sum(HourlyStats.waf_blocked), 0).label("threats_blocked"),
                func.coalesce(func.sum(HourlyStats.status_2xx), 0).label("status_2xx"),
                func.coalesce(func.sum(HourlyStats.status_3xx), 0).label("status_3xx"),
                func.coalesce(func.sum(HourlyStats.status_4xx), 0).label("status_4xx"),
                func.coalesce(func.sum(HourlyStats.status_5xx), 0).label("status_5xx"),
                func.coalesce(func.sum(HourlyStats.cache_hits), 0).label("cache_hits"),
            ).where(HourlyStats.hour >= start_time, HourlyStats.hour < current_hour_start)
            h_result = await db.execute(hourly_q)
            h_stats = h_result.one()

            raw_q = select(
                func.count(RequestLog.id).label("total_requests"),
                func.coalesce(func.sum(RequestLog.bytes_sent), 0).label("total_bandwidth"),
                func.count(case((RequestLog.waf_status == "blocked", 1))).label("threats_blocked"),
                func.count(case((RequestLog.status_code.between(200, 299), 1))).label("status_2xx"),
                func.count(case((RequestLog.status_code.between(300, 399), 1))).label("status_3xx"),
                func.count(case((RequestLog.status_code.between(400, 499), 1))).label("status_4xx"),
                func.count(case((RequestLog.status_code.between(500, 599), 1))).label("status_5xx"),
                func.count(case((RequestLog.cache_status == "HIT", 1))).label("cache_hits"),
            ).where(RequestLog.timestamp >= current_hour_start)
            r_result = await db.execute(raw_q)
            r_stats = r_result.one()

            class _MergedStats:
                pass
            stats = _MergedStats()
            for attr in ("total_requests", "total_bandwidth", "threats_blocked",
                         "status_2xx", "status_3xx", "status_4xx", "status_5xx", "cache_hits"):
                setattr(stats, attr, (getattr(h_stats, attr) or 0) + (getattr(r_stats, attr) or 0))
        else:
            query = select(
                func.count(RequestLog.id).label("total_requests"),
                func.sum(RequestLog.bytes_sent).label("total_bandwidth"),
                func.count(case((RequestLog.waf_status == "blocked", 1))).label("threats_blocked"),
                func.count(case((RequestLog.status_code.between(200, 299), 1))).label("status_2xx"),
                func.count(case((RequestLog.status_code.between(300, 399), 1))).label("status_3xx"),
                func.count(case((RequestLog.status_code.between(400, 499), 1))).label("status_4xx"),
                func.count(case((RequestLog.status_code.between(500, 599), 1))).label("status_5xx"),
                func.count(case((RequestLog.cache_status == "HIT", 1))).label("cache_hits"),
            ).where(RequestLog.timestamp >= start_time)
            result = await db.execute(query)
            stats = result.one()

        total_requests = stats.total_requests or 0
        cache_hits = stats.cache_hits or 0
        avg_cache_ratio = (cache_hits / total_requests * 100) if total_requests > 0 else 0.0

        domain_result = await db.execute(select(func.count(Domain.id)))
        total_domains = domain_result.scalar() or 0

        return {
            "total_requests": total_requests,
            "total_bandwidth": stats.total_bandwidth or 0,
            "avg_cache_ratio": round(avg_cache_ratio, 1),
            "threats_blocked": stats.threats_blocked or 0,
            "status_2xx": stats.status_2xx or 0,
            "status_3xx": stats.status_3xx or 0,
            "status_4xx": stats.status_4xx or 0,
            "status_5xx": stats.status_5xx or 0,
            "total_domains": total_domains,
        }

    @staticmethod
    async def get_timeseries_optimized(
        db: AsyncSession,
        range_str: str = "24h",
        metric: str = "requests",
        domain_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get timeseries data using aggregated tables when possible."""
        start_time = AnalyticsService.get_time_range_start(range_str)
        labels = []
        data = []

        if range_str in ["7d", "30d", "90d", "6m"]:
            start_date = start_time.date()
            query = select(
                DailyStats.day,
                func.sum(DailyStats.total_requests).label("count"),
                func.sum(DailyStats.total_bytes_sent).label("bytes"),
            ).where(DailyStats.day >= start_date)
            if domain_id:
                query = query.where(DailyStats.domain_id == domain_id)
            query = query.group_by(DailyStats.day).order_by(DailyStats.day)

            for row in (await db.execute(query)).all():
                labels.append(row.day.strftime("%m/%d"))
                data.append((row.bytes or 0) if metric == "bandwidth" else (row.count or 0))

        elif range_str == "24h":
            current_hour_start = datetime.utcnow().replace(minute=0, second=0, microsecond=0)

            query = select(
                HourlyStats.hour,
                func.sum(HourlyStats.total_requests).label("count"),
                func.sum(HourlyStats.total_bytes_sent).label("bytes"),
            ).where(
                HourlyStats.hour >= start_time,
                HourlyStats.hour < current_hour_start,
            )
            if domain_id:
                query = query.where(HourlyStats.domain_id == domain_id)
            query = query.group_by(HourlyStats.hour).order_by(HourlyStats.hour)

            for row in (await db.execute(query)).all():
                labels.append(row.hour.strftime("%H:00"))
                data.append((row.bytes or 0) if metric == "bandwidth" else (row.count or 0))

            raw_q = select(
                func.count(RequestLog.id).label("count"),
                func.coalesce(func.sum(RequestLog.bytes_sent), 0).label("bytes"),
            ).where(RequestLog.timestamp >= current_hour_start)
            if domain_id:
                raw_q = raw_q.where(RequestLog.domain_id == domain_id)
            raw_row = (await db.execute(raw_q)).one()
            if raw_row.count:
                labels.append(current_hour_start.strftime("%H:00"))
                data.append((raw_row.bytes or 0) if metric == "bandwidth" else (raw_row.count or 0))

        else:
            trunc_func = func.date_trunc("minute", RequestLog.timestamp)
            query = select(
                trunc_func.label("time_bucket"),
                func.count(RequestLog.id).label("count"),
                func.sum(RequestLog.bytes_sent).label("bytes"),
            ).where(RequestLog.timestamp >= start_time)
            if domain_id:
                query = query.where(RequestLog.domain_id == domain_id)
            query = query.group_by("time_bucket").order_by("time_bucket")

            try:
                for row in (await db.execute(query)).all():
                    if row.time_bucket:
                        labels.append(row.time_bucket.strftime("%H:%M"))
                        data.append((row.bytes or 0) if metric == "bandwidth" else (row.count or 0))
            except Exception as e:
                logger.error(f"Timeseries query failed: {e}")

        return {"labels": labels, "data": data}
