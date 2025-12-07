"""Internal API for edge nodes to pull configuration"""
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from app.core.database import get_db
from app.models.edge_node import EdgeNode
from app.models.domain import Domain
from app.models.origin import Origin
from app.models.cache import CacheRule
from app.models.waf import WAFRule, RateLimit
from app.models.certificate import Certificate
from app.models.log import RequestLog
from app.services.edge_service import EdgeNodeService

router = APIRouter()


async def verify_edge_node(
    x_node_id: int = Header(...),
    x_node_token: str = Header(...),
    db: AsyncSession = Depends(get_db)
) -> EdgeNode:
    """Verify edge node authentication"""
    node = await EdgeNodeService.get_node(db, x_node_id)
    
    if not node:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid node credentials"
        )
    
    if not node.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Node is disabled"
        )
    
    # Verify token
    if not x_node_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token"
        )
        
    if not node.api_key or node.api_key != x_node_token:
        # Backward compatibility for development: if node has no key set, maybe allow? 
        # No, security first. But since we just added the column, existing nodes have NULL.
        # We should generate keys for them or require regeneration.
        # For now, if node.api_key is None, we block.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token"
        )
    
    return node


@router.get("/config")
async def get_edge_config(
    since_version: Optional[int] = None,
    node: EdgeNode = Depends(verify_edge_node),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get configuration for edge node
    
    Headers:
    - X-Node-Id: Edge node ID
    - X-Node-Token: Authentication token
    
    Query params:
    - since_version: Only return config if version is newer
    """
    # Check if config version changed
    if since_version is not None and node.config_version <= since_version:
        return {
            "version": node.config_version,
            "changed": False
        }
    
    # Get all active domains (simplified - in production filter by node assignment)
    domains_result = await db.execute(
        select(Domain).where(Domain.status == "active")
    )
    domains = domains_result.scalars().all()
    
    config_domains = []
    
    for domain in domains:
        # Get origins
        origins_result = await db.execute(
            select(Origin).where(Origin.domain_id == domain.id, Origin.enabled == True)
        )
        origins = origins_result.scalars().all()
        
        # Get cache rules
        cache_rules_result = await db.execute(
            select(CacheRule).where(CacheRule.domain_id == domain.id, CacheRule.enabled == True)
        )
        cache_rules = cache_rules_result.scalars().all()
        
        # Get WAF rules
        waf_rules_result = await db.execute(
            select(WAFRule).where(WAFRule.domain_id == domain.id, WAFRule.enabled == True)
        )
        waf_rules = waf_rules_result.scalars().all()
        
        # Get rate limits
        rate_limits_result = await db.execute(
            select(RateLimit).where(RateLimit.domain_id == domain.id, RateLimit.enabled == True)
        )
        rate_limits = rate_limits_result.scalars().all()
        
        # Get certificate
        from app.models.certificate import CertificateStatus
        
        cert_result = await db.execute(
            select(Certificate).where(
                Certificate.domain_id == domain.id,
                Certificate.status == CertificateStatus.ISSUED
            ).order_by(Certificate.not_after.desc())
        )
        certificate = cert_result.scalar_one_or_none()
        
        domain_config = {
            "id": domain.id,
            "name": domain.name,
            "tls": {
                "enabled": bool(certificate),
                "certificate_id": certificate.id if certificate else None,
                "mode": getattr(domain, 'tls_mode', 'flexible'),
                "force_https": getattr(domain, 'force_https', True),
                "hsts_enabled": getattr(domain, 'hsts_enabled', False),
                "hsts_max_age": getattr(domain, 'hsts_max_age', 31536000)
            },
            "origins": [
                {
                    "id": origin.id,
                    "host": origin.origin_host,
                    "port": origin.origin_port,
                    "is_backup": origin.is_backup,
                    "weight": origin.weight,
                    "protocol": origin.protocol
                }
                for origin in origins
            ],
            "cache_rules": [
                {
                    "id": rule.id,
                    "pattern": rule.pattern,
                    "rule_type": rule.rule_type,
                    "ttl": rule.ttl,
                    "respect_origin": rule.respect_origin_headers,
                    "bypass_cookies": rule.bypass_cookies
                }
                for rule in cache_rules
            ],
            "waf_rules": [
                {
                    "id": rule.id,
                    "priority": rule.priority,
                    "action": rule.action,
                    "conditions": rule.conditions
                }
                for rule in waf_rules
            ],
            "rate_limits": [
                {
                    "id": limit.id,
                    "key_type": limit.key_type,
                    "limit": limit.limit_value,
                    "interval": limit.interval_seconds,
                    "action": limit.action
                }
                for limit in rate_limits
            ]
        }
        
        config_domains.append(domain_config)
    
    return {
        "version": node.config_version,
        "changed": True,
        "node": {
            "id": node.id,
            "name": node.name,
            "location": node.location_code
        },
        "domains": config_domains,
        "global_settings": {
            "log_level": "info",
            "worker_connections": 4096,
            "keepalive_timeout": 65
        }
    }


@router.post("/heartbeat")
async def edge_heartbeat(
    metrics: Dict[str, Any],
    node: EdgeNode = Depends(verify_edge_node),
    db: AsyncSession = Depends(get_db)
):
    """
    Receive heartbeat from edge node with metrics
    
    Body example:
    {
        "cpu_usage": 25.5,
        "memory_usage": 45.2,
        "disk_usage": 30.1,
        "active_connections": 150
    }
    """
    await EdgeNodeService.update_metrics(
        db,
        node.id,
        cpu_usage=metrics.get("cpu_usage"),
        memory_usage=metrics.get("memory_usage"),
        disk_usage=metrics.get("disk_usage")
    )
    
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/certificates/{cert_id}")
async def get_certificate(
    cert_id: int,
    node: EdgeNode = Depends(verify_edge_node),
    db: AsyncSession = Depends(get_db)
):
    """Get certificate content by ID"""
    result = await db.execute(
        select(Certificate).where(Certificate.id == cert_id)
    )
    cert = result.scalar_one_or_none()
    
    if not cert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Certificate not found"
        )
    
    return {
        "id": cert.id,
        "domain_id": cert.domain_id,
        "certificate": cert.cert_pem,
        "private_key": cert.key_pem,  # TODO: Decrypt
        "chain": cert.chain_pem,
        "not_before": cert.not_before.isoformat() if cert.not_before else None,
        "not_after": cert.not_after.isoformat() if cert.not_after else None
    }


@router.post("/logs")
async def receive_logs(
    logs: List[Dict[str, Any]],
    node: EdgeNode = Depends(verify_edge_node),
    db: AsyncSession = Depends(get_db)
):
    """
    Receive logs from edge node
    
    Body: Array of log entries
    [
        {
            "timestamp": "2024-01-01T12:00:00Z",
            "domain": "example.com",
            "path": "/api/test",
            "method": "GET",
            "status": 200,
            "bytes_sent": 1024,
            "client_ip": "1.2.3.4",
            "cache_status": "HIT"
        }
    ]
    """
    if not logs:
        return {"status": "ok", "received": 0}

    # Pre-fetch domains to minimize queries
    domain_names = list(set(log.get("domain") for log in logs if log.get("domain")))
    domains_map = {}
    
    if domain_names:
        domains_result = await db.execute(
            select(Domain).where(Domain.name.in_(domain_names))
        )
        domains_map = {d.name: d.id for d in domains_result.scalars().all()}
    
    log_entries = []
    for log_data in logs:
        domain_name = log_data.get("domain")
        domain_id = domains_map.get(domain_name)
        
        # Parse timestamp
        timestamp_str = log_data.get("timestamp")
        if timestamp_str:
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.utcnow()
        else:
            timestamp = datetime.utcnow()
        
        entry = RequestLog(
            timestamp=timestamp,
            domain_id=domain_id,
            edge_node_id=node.id,
            method=log_data.get("method"),
            path=log_data.get("path"),
            status_code=log_data.get("status"),
            bytes_sent=log_data.get("bytes_sent", 0),
            client_ip=log_data.get("client_ip"),
            cache_status=log_data.get("cache_status"),
            user_agent=log_data.get("user_agent"),
            referer=log_data.get("referer"),
            request_time=log_data.get("request_time"),
            country_code=log_data.get("country_code"),
            waf_status=log_data.get("waf_status"),
            waf_rule_id=log_data.get("waf_rule_id")
        )
        log_entries.append(entry)
    
    if log_entries:
        db.add_all(log_entries)
        await db.commit()
    
    return {
        "status": "ok",
        "received": len(logs),
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/health")
async def internal_health():
    """Simple health check for edge nodes"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat()
    }
