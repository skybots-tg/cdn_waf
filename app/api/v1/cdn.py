"""CDN settings API endpoints"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.models.domain import Domain
from app.schemas.cdn import (
    CacheRuleCreate,
    CacheRuleUpdate,
    CacheRuleResponse,
    CachePurgeRequest,
    CachePurgeResponse,
    DevModeResponse,
    OriginCreate,
    OriginUpdate,
    OriginResponse,
    CertificateCreate,
    CertificateResponse,
    TLSSettingsUpdate,
    TLSSettingsResponse
)
from app.services.cache_service import CacheService
from app.services.origin_service import OriginService
from app.services.ssl_service import SSLService
from app.core.security import get_current_active_user, require_domain_access

router = APIRouter()


# ==================== Cache Rules ====================

@router.get("/{domain_id}/cache/rules", response_model=List[CacheRuleResponse])
async def get_cache_rules(
    domain_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get cache rules for domain"""
    require_domain_access(current_user, domain_id)
    rules = await CacheService.get_rules(db, domain_id)
    return rules


@router.post("/{domain_id}/cache/rules", response_model=CacheRuleResponse)
async def create_cache_rule(
    domain_id: int,
    rule_data: CacheRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Create cache rule"""
    require_domain_access(current_user, domain_id)
    rule = await CacheService.create_rule(db, domain_id, rule_data)
    return rule


@router.patch("/cache/rules/{rule_id}", response_model=CacheRuleResponse)
async def update_cache_rule(
    rule_id: int,
    rule_data: CacheRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Update cache rule"""
    rule = await CacheService.update_rule(db, rule_id, rule_data)
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cache rule not found"
        )
    return rule


@router.delete("/cache/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cache_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Delete cache rule"""
    success = await CacheService.delete_rule(db, rule_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cache rule not found"
        )


# ==================== Cache Purge ====================

@router.post("/{domain_id}/cache/purge", response_model=CachePurgeResponse)
async def purge_cache(
    domain_id: int,
    purge_data: CachePurgeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Purge cache for domain"""
    require_domain_access(current_user, domain_id)
    if purge_data.purge_type == "all":
        purge = await CacheService.purge_all(db, domain_id, current_user.id)
    elif purge_data.purge_type == "url":
        if not purge_data.urls:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="URLs are required for URL purge"
            )
        purge = await CacheService.purge_by_url(
            db, domain_id, purge_data.urls, current_user.id
        )
    elif purge_data.purge_type == "pattern":
        if not purge_data.pattern:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Pattern is required for pattern purge"
            )
        purge = await CacheService.purge_by_pattern(
            db, domain_id, purge_data.pattern, current_user.id
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid purge type"
        )
    
    return purge


@router.get("/{domain_id}/cache/purge-history")
async def get_purge_history(
    domain_id: int,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get cache purge history"""
    require_domain_access(current_user, domain_id)
    history = await CacheService.get_purge_history(db, domain_id, limit)
    return history


# ==================== Dev Mode ====================

@router.post("/{domain_id}/cache/dev-mode", response_model=DevModeResponse)
async def enable_dev_mode(
    domain_id: int,
    duration_minutes: int = 10,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Enable dev mode (bypass cache)"""
    require_domain_access(current_user, domain_id)
    expires_at = await CacheService.enable_dev_mode(db, domain_id, duration_minutes)
    return DevModeResponse(
        enabled=True,
        expires_at=expires_at
    )


@router.delete("/{domain_id}/cache/dev-mode")
async def disable_dev_mode(
    domain_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Disable dev mode"""
    require_domain_access(current_user, domain_id)
    await CacheService.disable_dev_mode(db, domain_id)
    return {"status": "disabled"}


@router.get("/{domain_id}/cache/dev-mode", response_model=DevModeResponse)
async def get_dev_mode_status(
    domain_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get dev mode status"""
    require_domain_access(current_user, domain_id)
    is_active = await CacheService.is_dev_mode_active(db, domain_id)
    expires_at = await CacheService.get_dev_mode_expires(db, domain_id) if is_active else None
    
    return DevModeResponse(
        enabled=is_active,
        expires_at=expires_at
    )


# ==================== Origins ====================

@router.get("/{domain_id}/origins", response_model=List[OriginResponse])
async def get_origins(
    domain_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get origin servers for domain"""
    require_domain_access(current_user, domain_id)
    origins = await OriginService.get_origins(db, domain_id)
    return origins


@router.post("/{domain_id}/origins", response_model=OriginResponse)
async def create_origin(
    domain_id: int,
    origin_data: OriginCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Create origin server"""
    require_domain_access(current_user, domain_id)
    origin = await OriginService.create_origin(db, domain_id, origin_data)
    return origin


@router.patch("/origins/{origin_id}", response_model=OriginResponse)
async def update_origin(
    origin_id: int,
    origin_data: OriginUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Update origin server"""
    origin = await OriginService.update_origin(db, origin_id, origin_data)
    if not origin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Origin not found"
        )
    return origin


@router.delete("/origins/{origin_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_origin(
    origin_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Delete origin server"""
    success = await OriginService.delete_origin(db, origin_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Origin not found"
        )


@router.post("/origins/{origin_id}/health-check")
async def check_origin_health(
    origin_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Check origin server health"""
    health = await OriginService.check_health(db, origin_id)
    return health


# ==================== SSL/TLS Settings ====================

@router.post("/{domain_id}/ssl/upload", response_model=CertificateResponse)
async def upload_certificate(
    domain_id: int,
    cert_data: CertificateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    # Загрузить собственный SSL сертификат
    
    Используйте этот эндпоинт для загрузки собственного сертификата (не Let's Encrypt).
    Для автоматического выпуска Let's Encrypt используйте `/certificates/issue`.
    """
    require_domain_access(current_user, domain_id)
    try:
        cert = await SSLService.create_certificate(db, domain_id, cert_data)
        return cert
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/{domain_id}/ssl/settings", response_model=TLSSettingsResponse)
async def get_tls_settings(
    domain_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get TLS settings for domain"""
    require_domain_access(current_user, domain_id)
    from app.models.domain import DomainTLSSettings, TLSMode
    
    # Get TLS settings from database
    result = await db.execute(
        select(DomainTLSSettings).where(DomainTLSSettings.domain_id == domain_id)
    )
    tls_settings = result.scalar_one_or_none()
    
    # If settings don't exist, create default ones
    if not tls_settings:
        # Verify domain exists
        domain_result = await db.execute(
            select(Domain).where(Domain.id == domain_id)
        )
        domain = domain_result.scalar_one_or_none()
        if not domain:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Domain not found"
            )
        
        # Create default TLS settings
        tls_settings = DomainTLSSettings(
            domain_id=domain_id,
            mode=TLSMode.FLEXIBLE,
            force_https=False,  # Important: disable by default to avoid redirect loop
            hsts_enabled=False,
            hsts_max_age=31536000,
            hsts_include_subdomains=False,
            hsts_preload=False,
            min_tls_version="1.2",
            auto_certificate=True
        )
        db.add(tls_settings)
        await db.commit()
        await db.refresh(tls_settings)
    
    return TLSSettingsResponse(
        mode=tls_settings.mode.value,
        force_https=tls_settings.force_https,
        hsts_enabled=tls_settings.hsts_enabled,
        hsts_max_age=tls_settings.hsts_max_age,
        hsts_include_subdomains=tls_settings.hsts_include_subdomains,
        hsts_preload=tls_settings.hsts_preload,
        min_tls_version=tls_settings.min_tls_version
    )


@router.put("/{domain_id}/ssl/settings", response_model=TLSSettingsResponse)
async def update_tls_settings(
    domain_id: int,
    settings: TLSSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Update TLS settings for domain"""
    require_domain_access(current_user, domain_id)
    settings_dict = settings.model_dump(exclude_unset=True)
    success = await SSLService.update_tls_settings(db, domain_id, settings_dict)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domain not found"
        )
    
    # Return updated settings
    return await get_tls_settings(domain_id, db, current_user)
