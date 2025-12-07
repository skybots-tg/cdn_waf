"""Analytics API endpoints"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional

from app.core.database import get_db
from app.core.security import get_optional_current_user
from app.models.user import User
from app.models.domain import Domain
from app.models.edge_node import EdgeNode

router = APIRouter()


@router.get("/stats/global")
async def get_global_stats(
    range: str = "24h",
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get global statistics across all domains
    
    Note: Real-time statistics require request_logs table which will be implemented later.
    Currently returns zeros as no logs are stored yet.
    """
    # Count total domains
    result = await db.execute(select(func.count(Domain.id)))
    total_domains = result.scalar() or 0
    
    return {
        "total_requests": 0,
        "total_bandwidth": 0,
        "avg_cache_ratio": 0.0,
        "threats_blocked": 0,
        "status_2xx": 0,
        "status_3xx": 0,
        "status_4xx": 0,
        "status_5xx": 0,
        "total_domains": total_domains,
    }


@router.get("/stats/domains")
async def get_domains_stats(
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get statistics for all domains from database"""
    result = await db.execute(select(Domain))
    domains = result.scalars().all()
    
    return [
        {
            "id": domain.id,
            "name": domain.name,
            "status": domain.status.value,
            "requests": 0,  # Will be calculated from request_logs table when implemented
            "bandwidth": 0,  # Will be calculated from request_logs table when implemented
            "cache_ratio": 0.0  # Will be calculated from request_logs table when implemented
        }
        for domain in domains
    ]


@router.get("/stats/geo")
async def get_geo_stats(
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get geographic distribution statistics
    
    Note: Requires request_logs table with geo data. Returns empty until implemented.
    """
    return []


@router.get("/stats/edge-nodes")
async def get_edge_nodes_stats(
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get edge nodes performance statistics from database"""
    result = await db.execute(select(EdgeNode))
    nodes = result.scalars().all()
    
    return [
        {
            "id": node.id,
            "name": node.name,
            "location": node.location,
            "status": node.status.value,
            "requests": 0,  # Will be calculated from edge node metrics when implemented
            "avg_latency": 0,  # Will be calculated from edge node metrics when implemented
            "cpu_usage": 0  # Will be calculated from edge node metrics when implemented
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
    """Get basic statistics for a specific domain
    
    Note: Real statistics require request_logs table. Returns zeros until implemented.
    """
    # Verify domain exists
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    
    return {
        "total_requests": 0,
        "total_bandwidth": 0,
        "cache_hit_ratio": 0.0,
        "threats_blocked": 0,
        "status_2xx": 0,
        "status_3xx": 0,
        "status_4xx": 0,
        "status_5xx": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "cache_bypass": 0
    }


@router.get("/domains/{domain_id}/stats/top_paths")
async def get_domain_top_paths(
    domain_id: int,
    limit: int = 10,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get top paths for a specific domain
    
    Note: Requires request_logs table. Returns empty until implemented.
    """
    # Verify domain exists
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    
    return []


@router.get("/domains/{domain_id}/stats/geo")
async def get_domain_geo_stats(
    domain_id: int,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get geographic distribution for a specific domain
    
    Note: Requires request_logs table with geo data. Returns empty until implemented.
    """
    # Verify domain exists
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    
    return []


@router.get("/domains/{domain_id}/logs")
async def get_domain_logs(
    domain_id: int,
    limit: int = 100,
    offset: int = 0,
    status: Optional[int] = None,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get request logs for a specific domain
    
    Note: Requires request_logs table. Returns empty until implemented.
    """
    # Verify domain exists
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    
    return []
