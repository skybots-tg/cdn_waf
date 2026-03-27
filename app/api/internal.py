"""Internal API for edge nodes to pull configuration"""
import json
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from app.core.database import get_db
from app.core.config import settings
from app.models.edge_node import EdgeNode
from app.models.domain import Domain
from app.models.origin import Origin
from app.models.cache import CacheRule
from app.models.waf import WAFRule, RateLimit, IPAccessRule
from app.models.certificate import Certificate
from app.services.edge_service import EdgeNodeService

logger = logging.getLogger(__name__)

router = APIRouter()


def _parse_waf_conditions(conditions_str: str) -> Optional[Dict]:
    """Safely parse WAF rule conditions JSON string."""
    if not conditions_str:
        return None
    try:
        return json.loads(conditions_str) if isinstance(conditions_str, str) else conditions_str
    except (json.JSONDecodeError, TypeError):
        return None


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


@router.get("/debug-db")
async def debug_db_state(
    node: EdgeNode = Depends(verify_edge_node),
    db: AsyncSession = Depends(get_db)
):
    """Debug endpoint to check DB state (requires edge node auth)"""
    if not settings.DEBUG:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    domains_result = await db.execute(select(Domain))
    domains = domains_result.scalars().all()
    
    result = {"domains": []}
    for d in domains:
        origins_result = await db.execute(select(Origin).where(Origin.domain_id == d.id))
        origins = origins_result.scalars().all()
        
        result["domains"].append({
            "id": d.id,
            "name": d.name,
            "status": d.status,
            "origins": [
                {
                    "id": o.id,
                    "host": o.origin_host,
                    "enabled": o.enabled,
                    "domain_id": o.domain_id
                } for o in origins
            ]
        })
    return result


from app.models.dns import DNSRecord
from app.models.domain import DomainTLSSettings

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
    
    domains_result = await db.execute(
        select(Domain).where(Domain.status == "active")
    )
    domains = domains_result.scalars().all()
    logger.debug(f"Found {len(domains)} active domains")
    
    config_domains = []
    
    for domain in domains:
        # Get all A records for this domain (including root and subdomains)
        dns_records_result = await db.execute(
            select(DNSRecord).where(
                DNSRecord.domain_id == domain.id,
                DNSRecord.type == "A"
            )
        )
        dns_records = dns_records_result.scalars().all()
        
        # Map DNS records to virtual origin configurations
        # Group by subdomain name
        subdomains_map = {}
        
        # Add manually defined origins (usually root @)
        origins_result = await db.execute(
            select(Origin).where(Origin.domain_id == domain.id, Origin.enabled == True)
        )
        manual_origins = origins_result.scalars().all()
        
        # Use manual origins for root domain if available
        if manual_origins:
            subdomains_map["@"] = [
                {
                    "id": o.id,
                    "host": o.origin_host,
                    "port": o.origin_port,
                    "is_backup": o.is_backup,
                    "weight": o.weight,
                    "protocol": o.protocol
                } for o in manual_origins
            ]
            
        # Process DNS records to create virtual origins for subdomains
        for record in dns_records:
            if not record.content or record.proxied is False: 
                continue
                
            # Determine subdomain name ("@" or "sub")
            sub_name = record.name
            
            # If manual origins exist for this specific subdomain, skip DNS fallback?
            # Currently manual origins in DB don't have a "name" field that maps to subdomain (except name which is display name)
            # The Origin model lacks a 'hostname' or 'subdomain' field, it applies to the whole Domain object.
            # This is the root cause of the issue. Origins apply to the whole domain in current schema.
            
            # WORKAROUND: 
            # We will treat each DNS record as a separate "virtual domain config" 
            # so Nginx can generate a server block for IT specifically.
            
            if sub_name not in subdomains_map:
                subdomains_map[sub_name] = []
            
            # Add this IP as an origin for this subdomain
            subdomains_map[sub_name].append({
                "id": -(record.id * 10 + hash(sub_name) % 10),
                "host": record.content,
                "port": 80,
                "is_backup": False,
                "weight": record.weight or 100,
                "protocol": "http"
            })

        # Get other rules (shared across all subdomains for now)
        cache_rules_result = await db.execute(
            select(CacheRule).where(CacheRule.domain_id == domain.id, CacheRule.enabled == True)
        )
        cache_rules = cache_rules_result.scalars().all()
        
        waf_rules_result = await db.execute(
            select(WAFRule).where(WAFRule.domain_id == domain.id, WAFRule.enabled == True)
        )
        waf_rules = waf_rules_result.scalars().all()

        rate_limits_result = await db.execute(
            select(RateLimit).where(RateLimit.domain_id == domain.id, RateLimit.enabled == True)
        )
        rate_limits = rate_limits_result.scalars().all()

        # Load TLS settings from domain_tls_settings table
        tls_settings_result = await db.execute(
            select(DomainTLSSettings).where(DomainTLSSettings.domain_id == domain.id)
        )
        tls_settings = tls_settings_result.scalar_one_or_none()

        # Generate config for each subdomain found
        for sub_name, sub_origins in subdomains_map.items():
            if not sub_origins:
                continue
                
            # Construct full hostname
            if sub_name == "@":
                full_name = domain.name
            else:
                full_name = f"{sub_name}.{domain.name}"
            
            # Find certificate for this specific subdomain
            # Priority: 1) exact match, 2) wildcard cert, 3) root domain cert
            from app.models.certificate import CertificateStatus
            certificate = None
            
            # 1. Try exact match for this FQDN
            cert_result = await db.execute(
                select(Certificate).where(
                    Certificate.domain_id == domain.id,
                    Certificate.status == CertificateStatus.ISSUED,
                    Certificate.common_name == full_name
                ).order_by(Certificate.not_after.desc()).limit(1)
            )
            certificate = cert_result.scalar_one_or_none()
            
            # 2. If no exact match and this is a subdomain, try wildcard cert
            if not certificate and sub_name != "@":
                wildcard_name = f"*.{domain.name}"
                cert_result = await db.execute(
                    select(Certificate).where(
                        Certificate.domain_id == domain.id,
                        Certificate.status == CertificateStatus.ISSUED,
                        Certificate.common_name == wildcard_name
                    ).order_by(Certificate.not_after.desc()).limit(1)
                )
                certificate = cert_result.scalar_one_or_none()
            
            # 3. If still no cert and this is a subdomain, try root domain cert
            if not certificate and sub_name != "@":
                cert_result = await db.execute(
                    select(Certificate).where(
                        Certificate.domain_id == domain.id,
                        Certificate.status == CertificateStatus.ISSUED,
                        Certificate.common_name == domain.name
                    ).order_by(Certificate.not_after.desc()).limit(1)
                )
                certificate = cert_result.scalar_one_or_none()
                if certificate:
                    logger.debug(f"Using root domain certificate for {full_name}")
                
            domain_config = {
                "id": domain.id,
                "name": full_name, # Use specific subdomain as name for Nginx
                "tls": {
                    "enabled": bool(certificate),
                    "certificate_id": certificate.id if certificate else None,
                    "mode": tls_settings.mode.lower() if tls_settings else 'flexible',
                    "force_https": tls_settings.force_https if tls_settings else False,
                    "hsts_enabled": tls_settings.hsts_enabled if tls_settings else False,
                    "hsts_max_age": tls_settings.hsts_max_age if tls_settings else 31536000
                },
                "origins": sub_origins,
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
                "waf_enabled": bool(waf_rules),
                "waf_rules": [
                    {
                        "id": rule.id,
                        "name": rule.name,
                        "priority": rule.priority,
                        "action": rule.action.value if hasattr(rule.action, 'value') else rule.action,
                        "conditions": rule.conditions,
                        "conditions_parsed": _parse_waf_conditions(rule.conditions),
                    }
                    for rule in waf_rules
                ],
                "rate_limits": [
                    {
                        "id": rl.id,
                        "name": rl.name,
                        "path_pattern": rl.path_pattern,
                        "limit_value": rl.limit_value,
                        "interval_seconds": rl.interval_seconds,
                        "action": rl.action,
                        "response_status": rl.response_status,
                        "block_duration": rl.block_duration,
                    }
                    for rl in rate_limits
                ]
            }
            config_domains.append(domain_config)
    
    # Sort domains by name to ensure consistent order across all edge nodes
    # This prevents different edge nodes from having different default_server for HTTPS
    config_domains.sort(key=lambda d: d["name"])
    
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
            "keepalive_timeout": 65,
            "control_plane_url": settings.PUBLIC_URL
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
    
    from app.services.crypto_service import CryptoService
    key_pem = CryptoService.decrypt_if_encrypted(cert.key_pem)

    return {
        "id": cert.id,
        "domain_id": cert.domain_id,
        "certificate": cert.cert_pem,
        "private_key": key_pem,
        "chain": cert.chain_pem,
        "not_before": cert.not_before.isoformat() if cert.not_before else None,
        "not_after": cert.not_after.isoformat() if cert.not_after else None
    }


from app.api.internal_logs import router as logs_router
router.include_router(logs_router)
