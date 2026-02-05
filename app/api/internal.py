"""Internal API for edge nodes to pull configuration"""
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Header, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

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


@router.get("/debug-db")
async def debug_db_state(db: AsyncSession = Depends(get_db)):
    """Debug endpoint to check DB state"""
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
    
    # Debug: Check for all domains to see if some are pending
    all_domains_result = await db.execute(select(Domain))
    all_domains = all_domains_result.scalars().all()
    print(f"DEBUG: Total domains in DB: {len(all_domains)}")
    for d in all_domains:
        print(f"DEBUG: Domain: {d.name}, Status: {d.status}, ID: {d.id}")

    # Get all active domains (simplified - in production filter by node assignment)
    print("DEBUG: Fetching active domains")
    domains_result = await db.execute(
        select(Domain).where(Domain.status == "active")
    )
    domains = domains_result.scalars().all()
    print(f"DEBUG: Found {len(domains)} active domains")
    
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
                "id": record.id * 1000 + 555, # Fake ID
                "host": record.content,
                "port": 80, # Default port for DNS-based origin
                "is_backup": False,
                "weight": record.weight or 100,
                "protocol": "http" # Default protocol
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
                    print(f"DEBUG: Using root domain certificate for {full_name}")
                
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
                "waf_rules": [
                    {
                        "id": rule.id,
                        "priority": rule.priority,
                        "action": rule.action,
                        "conditions": rule.conditions
                    }
                    for rule in waf_rules
                ],
                "rate_limits": [] # Skipped for brevity
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
            "control_plane_url": "https://flarecloud.ru"
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
                # Ensure naive UTC for PostgreSQL
                if timestamp.tzinfo is not None:
                    timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
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


from app.core.redis import redis_client

@router.get("/acme-challenge/{token}", response_class=PlainTextResponse)
async def get_acme_challenge(
    token: str,
    node: EdgeNode = Depends(verify_edge_node)
):
    """Get ACME challenge response for edge nodes"""
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"ACME challenge request from edge node {node.name} for token: {token[:20]}...")
    
    validation = None
    if redis_client:
        key = f"acme:challenge:{token}"
        validation = await redis_client.get(key)
        logger.info(f"Redis lookup for key: {key}, found: {validation is not None}")
    
    if not validation:
        # List all keys for debugging
        if redis_client:
            import redis.asyncio as redis_lib
            all_keys = await redis_client.keys("acme:challenge:*")
            logger.warning(f"Challenge not found. Available keys: {all_keys}")
        
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Challenge not found"
        )
    
    # Return plain text (required by ACME spec)
    return PlainTextResponse(content=validation)


@router.get("/download/edge_config_updater.py", response_class=PlainTextResponse)
async def download_edge_config_updater(
    node: EdgeNode = Depends(verify_edge_node)
):
    """Download latest edge_config_updater.py for edge nodes"""
    import logging
    from pathlib import Path
    
    logger = logging.getLogger(__name__)
    logger.info(f"Edge node {node.name} requesting edge_config_updater.py download")
    
    # Simple authentication via shared key (from config.yaml on edge node)
    # You could also use verify_edge_node dependency, but this is simpler
    
    # Read the file
    updater_path = Path(__file__).parent.parent.parent / "edge_node" / "edge_config_updater.py"
    
    if not updater_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="edge_config_updater.py not found"
        )
    
    with open(updater_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    logger.info(f"Sending edge_config_updater.py ({len(content)} bytes)")
    
    return PlainTextResponse(content=content)
