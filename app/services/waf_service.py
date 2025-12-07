"""WAF and security management service"""
import logging
from typing import List, Optional, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.waf import WAFRule, RateLimit, IPAccessRule
from app.schemas.waf import (
    WAFRuleCreate,
    WAFRuleUpdate,
    RateLimitCreate,
    RateLimitUpdate,
    IPAccessRuleCreate,
    IPAccessRuleUpdate
)

logger = logging.getLogger(__name__)


class WAFService:
    """Service for managing WAF rules"""
    
    @staticmethod
    async def get_rules(
        db: AsyncSession,
        domain_id: int
    ) -> List[WAFRule]:
        """Get WAF rules for domain"""
        query = select(WAFRule).where(
            WAFRule.domain_id == domain_id
        ).order_by(WAFRule.priority.asc())
        
        result = await db.execute(query)
        return list(result.scalars().all())
    
    @staticmethod
    async def get_rule(db: AsyncSession, rule_id: int) -> Optional[WAFRule]:
        """Get WAF rule by ID"""
        result = await db.execute(
            select(WAFRule).where(WAFRule.id == rule_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def create_rule(
        db: AsyncSession,
        domain_id: int,
        rule_data: WAFRuleCreate
    ) -> WAFRule:
        """Create WAF rule"""
        rule = WAFRule(
            domain_id=domain_id,
            name=rule_data.name,
            priority=rule_data.priority,
            action=rule_data.action,
            conditions=rule_data.conditions,
            enabled=rule_data.enabled
        )
        
        db.add(rule)
        await db.commit()
        await db.refresh(rule)
        
        return rule
    
    @staticmethod
    async def update_rule(
        db: AsyncSession,
        rule_id: int,
        rule_data: WAFRuleUpdate
    ) -> Optional[WAFRule]:
        """Update WAF rule"""
        rule = await WAFService.get_rule(db, rule_id)
        if not rule:
            return None
        
        update_data = rule_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(rule, field):
                setattr(rule, field, value)
        
        await db.commit()
        await db.refresh(rule)
        
        return rule
    
    @staticmethod
    async def delete_rule(db: AsyncSession, rule_id: int) -> bool:
        """Delete WAF rule"""
        rule = await WAFService.get_rule(db, rule_id)
        if not rule:
            return False
        
        await db.delete(rule)
        await db.commit()
        return True
    
    @staticmethod
    async def get_rate_limits(
        db: AsyncSession,
        domain_id: int
    ) -> List[RateLimit]:
        """Get rate limits for domain"""
        query = select(RateLimit).where(
            RateLimit.domain_id == domain_id
        ).order_by(RateLimit.created_at.desc())
        
        result = await db.execute(query)
        return list(result.scalars().all())
    
    @staticmethod
    async def get_rate_limit(
        db: AsyncSession,
        limit_id: int
    ) -> Optional[RateLimit]:
        """Get rate limit by ID"""
        result = await db.execute(
            select(RateLimit).where(RateLimit.id == limit_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def create_rate_limit(
        db: AsyncSession,
        domain_id: int,
        limit_data: RateLimitCreate
    ) -> RateLimit:
        """Create rate limit"""
        rate_limit = RateLimit(
            domain_id=domain_id,
            name=limit_data.name,
            key_type=limit_data.key_type,
            limit_value=limit_data.limit_value,
            interval_seconds=limit_data.interval_seconds,
            action=limit_data.action,
            path_pattern=limit_data.path_pattern,
            enabled=limit_data.enabled
        )
        
        db.add(rate_limit)
        await db.commit()
        await db.refresh(rate_limit)
        
        return rate_limit
    
    @staticmethod
    async def update_rate_limit(
        db: AsyncSession,
        limit_id: int,
        limit_data: RateLimitUpdate
    ) -> Optional[RateLimit]:
        """Update rate limit"""
        rate_limit = await WAFService.get_rate_limit(db, limit_id)
        if not rate_limit:
            return None
        
        update_data = limit_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(rate_limit, field):
                setattr(rate_limit, field, value)
        
        await db.commit()
        await db.refresh(rate_limit)
        
        return rate_limit
    
    @staticmethod
    async def delete_rate_limit(db: AsyncSession, limit_id: int) -> bool:
        """Delete rate limit"""
        rate_limit = await WAFService.get_rate_limit(db, limit_id)
        if not rate_limit:
            return False
        
        await db.delete(rate_limit)
        await db.commit()
        return True
    
    @staticmethod
    async def get_ip_rules(
        db: AsyncSession,
        domain_id: int
    ) -> List[IPAccessRule]:
        """Get IP access rules for domain"""
        query = select(IPAccessRule).where(
            IPAccessRule.domain_id == domain_id
        ).order_by(IPAccessRule.created_at.desc())
        
        result = await db.execute(query)
        return list(result.scalars().all())
    
    @staticmethod
    async def get_ip_rule(
        db: AsyncSession,
        rule_id: int
    ) -> Optional[IPAccessRule]:
        """Get IP access rule by ID"""
        result = await db.execute(
            select(IPAccessRule).where(IPAccessRule.id == rule_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def create_ip_rule(
        db: AsyncSession,
        domain_id: int,
        rule_data: IPAccessRuleCreate
    ) -> IPAccessRule:
        """Create IP access rule"""
        ip_rule = IPAccessRule(
            domain_id=domain_id,
            rule_type=rule_data.rule_type,
            ip_address=rule_data.ip_address,
            description=rule_data.description,
            enabled=rule_data.enabled
        )
        
        db.add(ip_rule)
        await db.commit()
        await db.refresh(ip_rule)
        
        return ip_rule
    
    @staticmethod
    async def update_ip_rule(
        db: AsyncSession,
        rule_id: int,
        rule_data: IPAccessRuleUpdate
    ) -> Optional[IPAccessRule]:
        """Update IP access rule"""
        ip_rule = await WAFService.get_ip_rule(db, rule_id)
        if not ip_rule:
            return None
        
        update_data = rule_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(ip_rule, field):
                setattr(ip_rule, field, value)
        
        await db.commit()
        await db.refresh(ip_rule)
        
        return ip_rule
    
    @staticmethod
    async def delete_ip_rule(db: AsyncSession, rule_id: int) -> bool:
        """Delete IP access rule"""
        ip_rule = await WAFService.get_ip_rule(db, rule_id)
        if not ip_rule:
            return False
        
        await db.delete(ip_rule)
        await db.commit()
        return True
    
    @staticmethod
    async def enable_under_attack_mode(
        db: AsyncSession,
        domain_id: int
    ) -> bool:
        """Enable under attack mode for domain"""
        # Create aggressive rate limit
        rate_limit = RateLimit(
            domain_id=domain_id,
            name="Under Attack Mode",
            key_type="ip",
            limit_value=10,
            interval_seconds=60,
            action="challenge",
            enabled=True
        )
        
        db.add(rate_limit)
        await db.commit()
        return True
    
    @staticmethod
    async def disable_under_attack_mode(
        db: AsyncSession,
        domain_id: int
    ) -> bool:
        """Disable under attack mode for domain"""
        # Remove under attack mode rate limit
        result = await db.execute(
            select(RateLimit).where(
                RateLimit.domain_id == domain_id,
                RateLimit.name == "Under Attack Mode"
            )
        )
        
        for limit in result.scalars():
            await db.delete(limit)
        
        await db.commit()
        return True
