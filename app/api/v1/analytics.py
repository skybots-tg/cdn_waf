"""Analytics API endpoints with optimized aggregation support"""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case, desc
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, date
import csv
import io

from app.core.database import get_db
from app.core.security import get_optional_current_user, get_allowed_domain_ids, require_domain_access
from app.models.user import User
from app.models.domain import Domain
from app.models.edge_node import EdgeNode
from app.models.log import RequestLog
from app.models.analytics import HourlyStats, DailyStats, GeoStats, TopPathsStats, ErrorStats
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
    
    Time ranges:
    - 1h: Last hour (real-time from raw logs)
    - 24h: Last 24 hours (from hourly stats)
    - 7d: Last 7 days (from daily stats)
    - 30d: Last 30 days (from daily stats)
    - 90d: Last 90 days (from daily stats)
    - 6m: Last 6 months (from daily stats)
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
    
    # Get all domains
    domains_result = await db.execute(select(Domain))
    domains = list(domains_result.scalars().all())
    
    # Filter domains by API token restrictions if applicable
    if current_user:
        allowed_domain_ids = get_allowed_domain_ids(current_user)
        if allowed_domain_ids is not None:
            domains = [d for d in domains if d.id in allowed_domain_ids]
    
    # Use hourly stats for 24h and below, daily for 7d+
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
    
    # For 7d+, use geo stats table
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
        # Use raw logs for recent data
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
        {
            "country": row.country_code,
            "requests": row.requests
        }
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
    
    # Get request rates from hourly stats (last hour)
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
            "rps": round((row.count or 0) / 3600, 1),  # Convert to requests per second
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


@router.get("/domains/{domain_id}/stats/basic")
async def get_domain_basic_stats(
    domain_id: int,
    range: str = Query("24h", regex="^(1h|24h|7d|30d|90d|6m)$"),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get basic statistics for a specific domain using aggregated data"""
    if current_user:
        require_domain_access(current_user, domain_id)
    
    # Verify domain exists
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    
    start_time = AnalyticsService.get_time_range_start(range)
    
    # Use appropriate aggregation level
    if range in ["7d", "30d", "90d", "6m"]:
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
            func.sum(DailyStats.cache_misses).label("cache_misses"),
            func.sum(DailyStats.cache_bypass).label("cache_bypass")
        ).where(
            DailyStats.domain_id == domain_id,
            DailyStats.day >= start_date
        )
    elif range == "24h":
        query = select(
            func.sum(HourlyStats.total_requests).label("total_requests"),
            func.sum(HourlyStats.total_bytes_sent).label("total_bandwidth"),
            func.sum(HourlyStats.waf_blocked).label("threats_blocked"),
            func.sum(HourlyStats.status_2xx).label("status_2xx"),
            func.sum(HourlyStats.status_3xx).label("status_3xx"),
            func.sum(HourlyStats.status_4xx).label("status_4xx"),
            func.sum(HourlyStats.status_5xx).label("status_5xx"),
            func.sum(HourlyStats.cache_hits).label("cache_hits"),
            func.sum(HourlyStats.cache_misses).label("cache_misses"),
            func.sum(HourlyStats.cache_bypass).label("cache_bypass")
        ).where(
            HourlyStats.domain_id == domain_id,
            HourlyStats.hour >= start_time
        )
    else:
        # 1h - use raw logs
        query = select(
            func.count(RequestLog.id).label("total_requests"),
            func.sum(RequestLog.bytes_sent).label("total_bandwidth"),
            func.count(case((RequestLog.waf_status == "blocked", 1))).label("threats_blocked"),
            func.count(case((RequestLog.status_code.between(200, 299), 1))).label("status_2xx"),
            func.count(case((RequestLog.status_code.between(300, 399), 1))).label("status_3xx"),
            func.count(case((RequestLog.status_code.between(400, 499), 1))).label("status_4xx"),
            func.count(case((RequestLog.status_code.between(500, 599), 1))).label("status_5xx"),
            func.count(case((RequestLog.cache_status == "HIT", 1))).label("cache_hits"),
            func.count(case((RequestLog.cache_status == "MISS", 1))).label("cache_misses"),
            func.count(case((RequestLog.cache_status == "BYPASS", 1))).label("cache_bypass")
        ).where(
            RequestLog.domain_id == domain_id,
            RequestLog.timestamp >= start_time
        )
    
    stats_result = await db.execute(query)
    stats = stats_result.one()
    
    total_requests = stats.total_requests or 0
    cache_hits = stats.cache_hits or 0
    cache_hit_ratio = (cache_hits / total_requests * 100) if total_requests > 0 else 0.0
    
    return {
        "total_requests": total_requests,
        "total_bandwidth": stats.total_bandwidth or 0,
        "cache_hit_ratio": round(cache_hit_ratio, 1),
        "threats_blocked": stats.threats_blocked or 0,
        "status_2xx": stats.status_2xx or 0,
        "status_3xx": stats.status_3xx or 0,
        "status_4xx": stats.status_4xx or 0,
        "status_5xx": stats.status_5xx or 0,
        "cache_hits": cache_hits,
        "cache_misses": stats.cache_misses or 0,
        "cache_bypass": stats.cache_bypass or 0
    }


@router.get("/domains/{domain_id}/stats/timeseries")
async def get_domain_timeseries(
    domain_id: int,
    range: str = Query("24h", regex="^(1h|24h|7d|30d|90d|6m)$"),
    metric: str = Query("requests", regex="^(requests|bandwidth)$"),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get domain statistics timeseries using aggregated data"""
    if current_user:
        require_domain_access(current_user, domain_id)
    
    # Verify domain exists
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    
    return await AnalyticsService.get_timeseries_optimized(db, range, metric, domain_id)


@router.get("/domains/{domain_id}/stats/top_paths")
async def get_domain_top_paths(
    domain_id: int,
    range: str = Query("24h", regex="^(1h|24h|7d|30d)$"),
    limit: int = Query(10, ge=1, le=100),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get top paths for a specific domain from aggregated data"""
    if current_user:
        require_domain_access(current_user, domain_id)
    
    # Verify domain exists
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    
    start_time = AnalyticsService.get_time_range_start(range)
    
    # Use aggregated top_paths for 7d+
    if range in ["7d", "30d"]:
        start_date = start_time.date()
        query = select(
            TopPathsStats.path,
            func.sum(TopPathsStats.total_requests).label("requests"),
            func.sum(TopPathsStats.cache_hits).label("cache_hits"),
            func.sum(TopPathsStats.cache_misses).label("cache_misses")
        ).where(
            TopPathsStats.domain_id == domain_id,
            TopPathsStats.day >= start_date
        ).group_by(
            TopPathsStats.path
        ).order_by(
            desc("requests")
        ).limit(limit)
    else:
        # Use raw logs for recent data
        query = select(
            RequestLog.path,
            func.count(RequestLog.id).label("requests"),
            func.count(case((RequestLog.cache_status == "HIT", 1))).label("cache_hits"),
            func.count(case((RequestLog.cache_status == "MISS", 1))).label("cache_misses")
        ).where(
            RequestLog.domain_id == domain_id,
            RequestLog.timestamp >= start_time
        ).group_by(
            RequestLog.path
        ).order_by(
            desc("requests")
        ).limit(limit)
    
    result = await db.execute(query)
    
    return [
        {
            "path": row.path,
            "requests": row.requests,
            "cache_hits": row.cache_hits or 0,
            "cache_misses": row.cache_misses or 0
        }
        for row in result.all()
    ]


@router.get("/domains/{domain_id}/stats/errors")
async def get_domain_errors(
    domain_id: int,
    range: str = Query("24h", regex="^(1h|24h|7d|30d)$"),
    limit: int = Query(20, ge=1, le=100),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get top errors for a specific domain"""
    if current_user:
        require_domain_access(current_user, domain_id)
    
    # Verify domain exists
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    
    start_time = AnalyticsService.get_time_range_start(range)
    
    # Use aggregated error stats for 7d+
    if range in ["7d", "30d"]:
        start_date = start_time.date()
        query = select(
            ErrorStats.status_code,
            ErrorStats.path,
            func.sum(ErrorStats.error_count).label("count")
        ).where(
            ErrorStats.domain_id == domain_id,
            ErrorStats.day >= start_date
        ).group_by(
            ErrorStats.status_code,
            ErrorStats.path
        ).order_by(
            desc("count")
        ).limit(limit)
    else:
        # Use raw logs
        query = select(
            RequestLog.status_code,
            RequestLog.path,
            func.count(RequestLog.id).label("count")
        ).where(
            RequestLog.domain_id == domain_id,
            RequestLog.timestamp >= start_time,
            RequestLog.status_code >= 400
        ).group_by(
            RequestLog.status_code,
            RequestLog.path
        ).order_by(
            desc("count")
        ).limit(limit)
    
    result = await db.execute(query)
    
    return [
        {
            "status_code": row.status_code,
            "path": row.path,
            "count": row.count
        }
        for row in result.all()
    ]


@router.get("/domains/{domain_id}/stats/geo")
async def get_domain_geo_stats(
    domain_id: int,
    range: str = Query("24h", regex="^(1h|24h|7d|30d)$"),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get geographic distribution for a specific domain"""
    if current_user:
        require_domain_access(current_user, domain_id)
    
    # Verify domain exists
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    
    start_time = AnalyticsService.get_time_range_start(range)
    
    # Use aggregated geo stats for 7d+
    if range in ["7d", "30d"]:
        start_date = start_time.date()
        
        # Get total for percentage
        total_query = select(
            func.sum(GeoStats.total_requests)
        ).where(
            GeoStats.domain_id == domain_id,
            GeoStats.day >= start_date
        )
        total_result = await db.execute(total_query)
        total_requests = total_result.scalar() or 0
        
        query = select(
            GeoStats.country_code,
            func.sum(GeoStats.total_requests).label("requests"),
            func.sum(GeoStats.unique_visitors).label("visitors")
        ).where(
            GeoStats.domain_id == domain_id,
            GeoStats.day >= start_date,
            GeoStats.country_code.isnot(None)
        ).group_by(
            GeoStats.country_code
        ).order_by(
            desc("requests")
        ).limit(10)
    else:
        # Get total for percentage
        total_query = select(func.count(RequestLog.id)).where(
            RequestLog.domain_id == domain_id,
            RequestLog.timestamp >= start_time
        )
        total_result = await db.execute(total_query)
        total_requests = total_result.scalar() or 0
        
        query = select(
            RequestLog.country_code,
            func.count(RequestLog.id).label("requests"),
            func.count(func.distinct(RequestLog.client_ip)).label("visitors")
        ).where(
            RequestLog.domain_id == domain_id,
            RequestLog.timestamp >= start_time,
            RequestLog.country_code.isnot(None)
        ).group_by(
            RequestLog.country_code
        ).order_by(
            desc("requests")
        ).limit(10)
    
    result = await db.execute(query)
    
    return [
        {
            "country": row.country_code,
            "requests": row.requests,
            "visitors": row.visitors or 0,
            "percentage": round(row.requests / total_requests * 100, 1) if total_requests > 0 else 0
        }
        for row in result.all()
    ]


@router.get("/domains/{domain_id}/logs")
async def get_domain_logs(
    domain_id: int,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    status: Optional[int] = None,
    method: Optional[str] = None,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get request logs for a specific domain (raw logs, last 30 days)"""
    if current_user:
        require_domain_access(current_user, domain_id)
    
    # Verify domain exists
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    
    query = select(RequestLog).where(
        RequestLog.domain_id == domain_id
    )
    
    if status:
        query = query.where(RequestLog.status_code == status)
    
    if method:
        query = query.where(RequestLog.method == method.upper())
        
    query = query.order_by(RequestLog.timestamp.desc()).offset(offset).limit(limit)
    
    result = await db.execute(query)
    logs = result.scalars().all()
    
    return [
        {
            "id": log.id,
            "timestamp": log.timestamp.isoformat(),
            "method": log.method,
            "path": log.path,
            "status": log.status_code,
            "client_ip": log.client_ip,
            "bytes_sent": log.bytes_sent,
            "cache_status": log.cache_status,
            "country_code": log.country_code,
            "request_time": log.request_time,
            "user_agent": log.user_agent[:100] if log.user_agent else None
        }
        for log in logs
    ]


@router.get("/domains/{domain_id}/export")
async def export_domain_analytics(
    domain_id: int,
    range: str = Query("24h", regex="^(1h|24h|7d|30d)$"),
    format: str = Query("csv", regex="^(csv|json)$"),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Export domain analytics data"""
    if current_user:
        require_domain_access(current_user, domain_id)
    
    # Verify domain exists
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    
    start_time = AnalyticsService.get_time_range_start(range)
    
    # Get timeseries data
    timeseries = await AnalyticsService.get_timeseries_optimized(db, range, "requests", domain_id)
    bandwidth = await AnalyticsService.get_timeseries_optimized(db, range, "bandwidth", domain_id)
    
    # Get basic stats
    stats_result = await db.execute(
        select(
            func.count(RequestLog.id).label("total_requests"),
            func.sum(RequestLog.bytes_sent).label("total_bandwidth")
        ).where(
            RequestLog.domain_id == domain_id,
            RequestLog.timestamp >= start_time
        )
    )
    stats = stats_result.one()
    
    if format == "json":
        return {
            "domain": domain.name,
            "range": range,
            "exported_at": datetime.utcnow().isoformat(),
            "summary": {
                "total_requests": stats.total_requests or 0,
                "total_bandwidth": stats.total_bandwidth or 0
            },
            "timeseries": {
                "labels": timeseries["labels"],
                "requests": timeseries["data"],
                "bandwidth": bandwidth["data"]
            }
        }
    else:
        # CSV format
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow(["Time", "Requests", "Bandwidth (bytes)"])
        
        # Data rows
        for i, label in enumerate(timeseries["labels"]):
            writer.writerow([
                label,
                timeseries["data"][i] if i < len(timeseries["data"]) else 0,
                bandwidth["data"][i] if i < len(bandwidth["data"]) else 0
            ])
        
        output.seek(0)
        
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={domain.name}_analytics_{range}.csv"
            }
        )


@router.get("/export/global")
async def export_global_analytics(
    range: str = Query("24h", regex="^(1h|24h|7d|30d)$"),
    format: str = Query("csv", regex="^(csv|json)$"),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Export global analytics data"""
    # Get global stats
    stats = await AnalyticsService.get_global_stats_optimized(db, range)
    timeseries = await AnalyticsService.get_timeseries_optimized(db, range, "requests")
    bandwidth = await AnalyticsService.get_timeseries_optimized(db, range, "bandwidth")
    
    if format == "json":
        return {
            "range": range,
            "exported_at": datetime.utcnow().isoformat(),
            "summary": stats,
            "timeseries": {
                "labels": timeseries["labels"],
                "requests": timeseries["data"],
                "bandwidth": bandwidth["data"]
            }
        }
    else:
        # CSV format
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow(["Time", "Requests", "Bandwidth (bytes)"])
        
        # Data rows
        for i, label in enumerate(timeseries["labels"]):
            writer.writerow([
                label,
                timeseries["data"][i] if i < len(timeseries["data"]) else 0,
                bandwidth["data"][i] if i < len(bandwidth["data"]) else 0
            ])
        
        output.seek(0)
        
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=global_analytics_{range}.csv"
            }
        )
