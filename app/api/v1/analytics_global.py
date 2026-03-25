"""Global analytics endpoints (stats, geo, edge nodes, domain summaries)"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from typing import Optional
from datetime import datetime, timedelta

from app.core.database import get_db
from app.core.security import get_optional_current_user, get_allowed_domain_ids
from app.models.user import User
from app.models.domain import Domain
from app.models.edge_node import EdgeNode
from app.models.log import RequestLog
from app.models.analytics import HourlyStats, DailyStats, GeoStats
from app.services.analytics_service import AnalyticsService

router = APIRouter()


@router.get("/stats/global")
async def get_global_stats(
    range: str = Query("24h", regex="^(1h|24h|7d|30d|90d|6m)$"),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get global statistics across all domains.
    Uses aggregated data for longer time ranges for better performance.
    """
    return await AnalyticsService.get_global_stats_optimized(db, range)


@router.get("/stats/global/timeseries")
async def get_global_timeseries(
    range: str = Query("24h", regex="^(1h|24h|7d|30d|90d|6m)$"),
    metric: str = Query("requests", regex="^(requests|bandwidth)$"),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get global statistics timeseries using aggregated data"""
    return await AnalyticsService.get_timeseries_optimized(db, range, metric)


@router.get("/stats/domains")
async def get_domains_stats(
    range: str = Query("24h", regex="^(1h|24h|7d|30d)$"),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get statistics for all domains from aggregated data"""
    start_time = AnalyticsService.get_time_range_start(range)

    domains_result = await db.execute(select(Domain))
    domains = list(domains_result.scalars().all())

    if current_user:
        allowed_domain_ids = get_allowed_domain_ids(current_user)
        if allowed_domain_ids is not None:
            domains = [d for d in domains if d.id in allowed_domain_ids]

    if range in ["7d", "30d"]:
        start_date = start_time.date()
        stats_query = select(
            DailyStats.domain_id,
            func.sum(DailyStats.total_requests).label("requests"),
            func.sum(DailyStats.total_bytes_sent).label("bandwidth"),
            func.sum(DailyStats.cache_hits).label("cache_hits")
        ).where(
            DailyStats.day >= start_date
        ).group_by(DailyStats.domain_id)
    else:
        stats_query = select(
            HourlyStats.domain_id,
            func.sum(HourlyStats.total_requests).label("requests"),
            func.sum(HourlyStats.total_bytes_sent).label("bandwidth"),
            func.sum(HourlyStats.cache_hits).label("cache_hits")
        ).where(
            HourlyStats.hour >= start_time
        ).group_by(HourlyStats.domain_id)

    stats_result = await db.execute(stats_query)
    stats_map = {
        row.domain_id: {
            "requests": row.requests or 0,
            "bandwidth": row.bandwidth or 0,
            "cache_hits": row.cache_hits or 0
        }
        for row in stats_result.all()
    }

    result = []
    for domain in domains:
        d_stats = stats_map.get(domain.id, {"requests": 0, "bandwidth": 0, "cache_hits": 0})
        total_reqs = d_stats["requests"]
        cache_hits = d_stats["cache_hits"]
        cache_ratio = (cache_hits / total_reqs * 100) if total_reqs > 0 else 0.0

        result.append({
            "id": domain.id,
            "name": domain.name,
            "status": domain.status.value,
            "requests": total_reqs,
            "bandwidth": d_stats["bandwidth"],
            "cache_ratio": round(cache_ratio, 1)
        })

    return result


@router.get("/stats/geo")
async def get_geo_stats(
    range: str = Query("24h", regex="^(1h|24h|7d|30d)$"),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get geographic distribution statistics from aggregated data"""
    start_time = AnalyticsService.get_time_range_start(range)

    if range in ["7d", "30d"]:
        start_date = start_time.date()
        query = select(
            GeoStats.country_code,
            func.sum(GeoStats.total_requests).label("requests")
        ).where(
            GeoStats.day >= start_date,
            GeoStats.country_code.isnot(None)
        ).group_by(
            GeoStats.country_code
        ).order_by(
            desc("requests")
        ).limit(10)
    else:
        query = select(
            RequestLog.country_code,
            func.count(RequestLog.id).label("requests")
        ).where(
            RequestLog.timestamp >= start_time,
            RequestLog.country_code.isnot(None)
        ).group_by(
            RequestLog.country_code
        ).order_by(
            desc("requests")
        ).limit(10)

    result = await db.execute(query)

    return [
        {"country": row.country_code, "requests": row.requests}
        for row in result.all()
    ]


@router.get("/stats/edge-nodes")
async def get_edge_nodes_stats(
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get edge nodes performance statistics"""
    result = await db.execute(select(EdgeNode))
    nodes = result.scalars().all()

    hour_ago = datetime.utcnow() - timedelta(hours=1)

    rps_query = select(
        HourlyStats.edge_node_id,
        func.sum(HourlyStats.total_requests).label("count"),
        func.avg(HourlyStats.avg_response_time).label("avg_latency")
    ).where(
        HourlyStats.hour >= hour_ago
    ).group_by(HourlyStats.edge_node_id)

    rps_result = await db.execute(rps_query)
    rps_map = {
        row.edge_node_id: {
            "rps": round((row.count or 0) / 3600, 1),
            "latency": round(row.avg_latency or 0, 1)
        }
        for row in rps_result.all()
    }

    return [
        {
            "id": node.id,
            "name": node.name,
            "location": node.location_code,
            "status": node.status,
            "requests": rps_map.get(node.id, {}).get("rps", 0),
            "avg_latency": rps_map.get(node.id, {}).get("latency", 0),
            "cpu_usage": node.cpu_usage or 0
        }
        for node in nodes
    ]
