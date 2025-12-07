"""Analytics API endpoints"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case, desc
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from app.core.database import get_db
from app.core.security import get_optional_current_user
from app.models.user import User
from app.models.domain import Domain
from app.models.edge_node import EdgeNode
from app.models.log import RequestLog

router = APIRouter()


def get_time_range_start(range_str: str) -> datetime:
    now = datetime.utcnow()
    if range_str == "1h":
        return now - timedelta(hours=1)
    elif range_str == "24h":
        return now - timedelta(days=1)
    elif range_str == "7d":
        return now - timedelta(days=7)
    elif range_str == "30d":
        return now - timedelta(days=30)
    return now - timedelta(days=1)


@router.get("/stats/global")
async def get_global_stats(
    range: str = "24h",
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get global statistics across all domains"""
    start_time = get_time_range_start(range)
    
    # Base query
    query = select(
        func.count(RequestLog.id).label("total_requests"),
        func.sum(RequestLog.bytes_sent).label("total_bandwidth"),
        func.count(case((RequestLog.waf_status == "blocked", 1))).label("threats_blocked"),
        func.count(case((RequestLog.status_code.between(200, 299), 1))).label("status_2xx"),
        func.count(case((RequestLog.status_code.between(300, 399), 1))).label("status_3xx"),
        func.count(case((RequestLog.status_code.between(400, 499), 1))).label("status_4xx"),
        func.count(case((RequestLog.status_code.between(500, 599), 1))).label("status_5xx"),
        func.count(case((RequestLog.cache_status == "HIT", 1))).label("cache_hits")
    ).where(RequestLog.timestamp >= start_time)
    
    result = await db.execute(query)
    stats = result.one()
    
    total_requests = stats.total_requests or 0
    cache_hits = stats.cache_hits or 0
    avg_cache_ratio = (cache_hits / total_requests * 100) if total_requests > 0 else 0.0
    
    # Count total domains
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


@router.get("/stats/global/timeseries")
async def get_global_timeseries(
    range: str = "24h",
    metric: str = "requests",
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get global statistics timeseries"""
    start_time = get_time_range_start(range)
    
    trunc_interval = 'minute' if range == '1h' else 'hour'
    
    # Use generic grouping if database type is unknown or support both?
    # For now assuming Postgres with date_trunc
    trunc_func = func.date_trunc(trunc_interval, RequestLog.timestamp)
    
    query = select(
        trunc_func.label("time_bucket"),
        func.count(RequestLog.id).label("count"),
        func.sum(RequestLog.bytes_sent).label("bytes")
    ).where(
        RequestLog.timestamp >= start_time
    ).group_by(
        "time_bucket"
    ).order_by(
        "time_bucket"
    )
    
    try:
        result = await db.execute(query)
        rows = result.all()
    except Exception as e:
        print(f"Timeseries query failed (likely DB specific function): {e}")
        return {"labels": [], "data": []}

    labels = []
    data = []
    
    for row in rows:
        dt = row.time_bucket
        if not dt: continue
        
        if range == '1h':
            label = dt.strftime("%H:%M")
        else:
            label = dt.strftime("%H:00")
            
        labels.append(label)
        
        if metric == 'bandwidth':
            data.append(row.bytes or 0)
        else:
            data.append(row.count or 0)
            
    return {
        "labels": labels,
        "data": data
    }


@router.get("/stats/domains")
async def get_domains_stats(
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get statistics for all domains from database"""
    # Get all domains
    domains_result = await db.execute(select(Domain))
    domains = domains_result.scalars().all()
    
    # Calculate stats for each domain (could be optimized with group by query)
    # Using group by query is better
    stats_query = select(
        RequestLog.domain_id,
        func.count(RequestLog.id).label("requests"),
        func.sum(RequestLog.bytes_sent).label("bandwidth"),
        func.count(case((RequestLog.cache_status == "HIT", 1))).label("cache_hits")
    ).where(
        RequestLog.timestamp >= get_time_range_start("24h")
    ).group_by(RequestLog.domain_id)
    
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
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get geographic distribution statistics"""
    start_time = get_time_range_start("24h")
    
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
    """Get edge nodes performance statistics from database"""
    result = await db.execute(select(EdgeNode))
    nodes = result.scalars().all()
    
    # Get request rates from logs (last 5 mins avg)
    # This is a bit heavy, maybe rely on heartbeat metrics if they included RPS
    # For now, let's just count requests in last 5 min / 300s
    start_time = datetime.utcnow() - timedelta(minutes=5)
    
    rps_query = select(
        RequestLog.edge_node_id,
        func.count(RequestLog.id).label("count")
    ).where(
        RequestLog.timestamp >= start_time
    ).group_by(RequestLog.edge_node_id)
    
    rps_result = await db.execute(rps_query)
    rps_map = {row.edge_node_id: round(row.count / 300, 1) for row in rps_result.all()}
    
    return [
        {
            "id": node.id,
            "name": node.name,
            "location": node.location_code,
            "status": node.status,
            "requests": rps_map.get(node.id, 0),
            "avg_latency": 0,  # We don't have this in metrics yet, maybe in logs 'request_time'
            "cpu_usage": node.cpu_usage or 0
        }
        for node in nodes
    ]


@router.get("/domains/{domain_id}/stats/basic")
async def get_domain_basic_stats(
    domain_id: int,
    range: str = "24h",
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get basic statistics for a specific domain"""
    # Verify domain exists
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
        
    start_time = get_time_range_start(range)
    
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
    range: str = "24h",
    metric: str = "requests",
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get domain statistics timeseries"""
    # Verify domain exists
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")

    start_time = get_time_range_start(range)
    
    trunc_interval = 'minute' if range == '1h' else 'hour'
    trunc_func = func.date_trunc(trunc_interval, RequestLog.timestamp)
    
    query = select(
        trunc_func.label("time_bucket"),
        func.count(RequestLog.id).label("count"),
        func.sum(RequestLog.bytes_sent).label("bytes")
    ).where(
        RequestLog.domain_id == domain_id,
        RequestLog.timestamp >= start_time
    ).group_by(
        "time_bucket"
    ).order_by(
        "time_bucket"
    )
    
    try:
        result = await db.execute(query)
        rows = result.all()
    except Exception as e:
        print(f"Timeseries query failed: {e}")
        return {"labels": [], "data": []}

    labels = []
    data = []
    
    for row in rows:
        dt = row.time_bucket
        if not dt: continue
        
        if range == '1h':
            label = dt.strftime("%H:%M")
        else:
            label = dt.strftime("%H:00")
            
        labels.append(label)
        
        if metric == 'bandwidth':
            data.append(row.bytes or 0)
        else:
            data.append(row.count or 0)
            
    return {
        "labels": labels,
        "data": data
    }


@router.get("/domains/{domain_id}/stats/top_paths")
async def get_domain_top_paths(
    domain_id: int,
    limit: int = 10,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get top paths for a specific domain"""
    # Verify domain exists
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
        
    start_time = get_time_range_start("24h")
    
    query = select(
        RequestLog.path,
        func.count(RequestLog.id).label("requests")
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
            "requests": row.requests
        }
        for row in result.all()
    ]


@router.get("/domains/{domain_id}/stats/geo")
async def get_domain_geo_stats(
    domain_id: int,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get geographic distribution for a specific domain"""
    # Verify domain exists
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
        
    start_time = get_time_range_start("24h")
    
    # Get total requests for percentage calculation
    total_query = select(func.count(RequestLog.id)).where(
        RequestLog.domain_id == domain_id,
        RequestLog.timestamp >= start_time
    )
    total_result = await db.execute(total_query)
    total_requests = total_result.scalar() or 0
    
    query = select(
        RequestLog.country_code,
        func.count(RequestLog.id).label("requests")
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
            "percentage": round(row.requests / total_requests * 100, 1) if total_requests > 0 else 0
        }
        for row in result.all()
    ]


@router.get("/domains/{domain_id}/logs")
async def get_domain_logs(
    domain_id: int,
    limit: int = 100,
    offset: int = 0,
    status: Optional[int] = None,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get request logs for a specific domain"""
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
            "cache_status": log.cache_status
        }
        for log in logs
    ]
