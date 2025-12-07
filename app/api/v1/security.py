"""WAF and security API endpoints"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.schemas.waf import (
    WAFRuleCreate,
    WAFRuleUpdate,
    WAFRuleResponse,
    RateLimitCreate,
    RateLimitUpdate,
    RateLimitResponse,
    IPAccessRuleCreate,
    IPAccessRuleUpdate,
    IPAccessRuleResponse
)
from app.services.waf_service import WAFService
from app.api.deps import get_current_active_user

router = APIRouter()


# ==================== WAF Rules ====================

@router.get("/{domain_id}/waf/rules", response_model=List[WAFRuleResponse])
async def get_waf_rules(
    domain_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get WAF rules for domain"""
    rules = await WAFService.get_rules(db, domain_id)
    return rules


@router.post("/{domain_id}/waf/rules", response_model=WAFRuleResponse)
async def create_waf_rule(
    domain_id: int,
    rule_data: WAFRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Create WAF rule"""
    rule = await WAFService.create_rule(db, domain_id, rule_data)
    return rule


@router.patch("/waf/rules/{rule_id}", response_model=WAFRuleResponse)
async def update_waf_rule(
    rule_id: int,
    rule_data: WAFRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Update WAF rule"""
    rule = await WAFService.update_rule(db, rule_id, rule_data)
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WAF rule not found"
        )
    return rule


@router.delete("/waf/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_waf_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Delete WAF rule"""
    success = await WAFService.delete_rule(db, rule_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WAF rule not found"
        )


# ==================== Rate Limits ====================

@router.get("/{domain_id}/rate-limits", response_model=List[RateLimitResponse])
async def get_rate_limits(
    domain_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get rate limits for domain"""
    limits = await WAFService.get_rate_limits(db, domain_id)
    return limits


@router.post("/{domain_id}/rate-limits", response_model=RateLimitResponse)
async def create_rate_limit(
    domain_id: int,
    limit_data: RateLimitCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Create rate limit"""
    limit = await WAFService.create_rate_limit(db, domain_id, limit_data)
    return limit


@router.patch("/rate-limits/{limit_id}", response_model=RateLimitResponse)
async def update_rate_limit(
    limit_id: int,
    limit_data: RateLimitUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Update rate limit"""
    limit = await WAFService.update_rate_limit(db, limit_id, limit_data)
    if not limit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rate limit not found"
        )
    return limit


@router.delete("/rate-limits/{limit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rate_limit(
    limit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Delete rate limit"""
    success = await WAFService.delete_rate_limit(db, limit_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rate limit not found"
        )


# ==================== IP Access Rules ====================

@router.get("/{domain_id}/ip-rules", response_model=List[IPAccessRuleResponse])
async def get_ip_rules(
    domain_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get IP access rules for domain"""
    rules = await WAFService.get_ip_rules(db, domain_id)
    return rules


@router.post("/{domain_id}/ip-rules", response_model=IPAccessRuleResponse)
async def create_ip_rule(
    domain_id: int,
    rule_data: IPAccessRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Create IP access rule"""
    rule = await WAFService.create_ip_rule(db, domain_id, rule_data)
    return rule


@router.patch("/ip-rules/{rule_id}", response_model=IPAccessRuleResponse)
async def update_ip_rule(
    rule_id: int,
    rule_data: IPAccessRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Update IP access rule"""
    rule = await WAFService.update_ip_rule(db, rule_id, rule_data)
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="IP access rule not found"
        )
    return rule


@router.delete("/ip-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ip_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Delete IP access rule"""
    success = await WAFService.delete_ip_rule(db, rule_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="IP access rule not found"
        )


# ==================== Under Attack Mode ====================

@router.post("/{domain_id}/under-attack-mode")
async def enable_under_attack_mode(
    domain_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Enable under attack mode for domain"""
    await WAFService.enable_under_attack_mode(db, domain_id)
    return {"status": "enabled", "message": "Under attack mode enabled"}


@router.delete("/{domain_id}/under-attack-mode")
async def disable_under_attack_mode(
    domain_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Disable under attack mode for domain"""
    await WAFService.disable_under_attack_mode(db, domain_id)
    return {"status": "disabled", "message": "Under attack mode disabled"}
