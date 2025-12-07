"""Cache management service"""
import logging
from typing import List, Optional
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cache import CacheRule, CachePurge
from app.models.domain import Domain
from app.core.redis import redis_client
from app.schemas.cdn import CacheRuleCreate, CacheRuleUpdate

logger = logging.getLogger(__name__)


class CacheService:
    """Service for managing cache rules and operations"""
    
    @staticmethod
    async def get_rules(
        db: AsyncSession,
        domain_id: int,
        skip: int = 0,
        limit: int = 100
    ) -> List[CacheRule]:
        """Get cache rules for domain"""
        query = select(CacheRule).where(
            CacheRule.domain_id == domain_id
        ).offset(skip).limit(limit).order_by(CacheRule.priority.asc())
        
        result = await db.execute(query)
        return list(result.scalars().all())
    
    @staticmethod
    async def get_rule(db: AsyncSession, rule_id: int) -> Optional[CacheRule]:
        """Get cache rule by ID"""
        result = await db.execute(
            select(CacheRule).where(CacheRule.id == rule_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def create_rule(
        db: AsyncSession,
        domain_id: int,
        rule_data: CacheRuleCreate
    ) -> CacheRule:
        """Create cache rule"""
        import json
        
        rule = CacheRule(
            domain_id=domain_id,
            pattern=rule_data.pattern,
            rule_type=rule_data.rule_type,
            ttl=rule_data.ttl,
            priority=rule_data.priority,
            respect_origin_headers=rule_data.respect_origin_headers,
            bypass_cookies=json.dumps(rule_data.bypass_cookies) if rule_data.bypass_cookies else None,
            bypass_query_params=json.dumps(rule_data.bypass_query_params) if rule_data.bypass_query_params else None,
            enabled=rule_data.enabled
        )
        
        db.add(rule)
        await db.commit()
        await db.refresh(rule)
        
        # Trigger config update for edge nodes
        await CacheService._trigger_config_update(domain_id)
        
        return rule
    
    @staticmethod
    async def update_rule(
        db: AsyncSession,
        rule_id: int,
        rule_data: CacheRuleUpdate
    ) -> Optional[CacheRule]:
        """Update cache rule"""
        import json
        
        rule = await CacheService.get_rule(db, rule_id)
        if not rule:
            return None
        
        update_data = rule_data.model_dump(exclude_unset=True)
        
        # JSON-serialize list fields
        if 'bypass_cookies' in update_data and update_data['bypass_cookies'] is not None:
            update_data['bypass_cookies'] = json.dumps(update_data['bypass_cookies'])
        if 'bypass_query_params' in update_data and update_data['bypass_query_params'] is not None:
            update_data['bypass_query_params'] = json.dumps(update_data['bypass_query_params'])
        
        for field, value in update_data.items():
            if hasattr(rule, field):
                setattr(rule, field, value)
        
        await db.commit()
        await db.refresh(rule)
        
        # Trigger config update
        await CacheService._trigger_config_update(rule.domain_id)
        
        return rule
    
    @staticmethod
    async def delete_rule(db: AsyncSession, rule_id: int) -> bool:
        """Delete cache rule"""
        rule = await CacheService.get_rule(db, rule_id)
        if not rule:
            return False
        
        domain_id = rule.domain_id
        await db.delete(rule)
        await db.commit()
        
        await CacheService._trigger_config_update(domain_id)
        return True
    
    @staticmethod
    async def purge_all(
        db: AsyncSession,
        domain_id: int,
        initiated_by: int
    ) -> CachePurge:
        """Purge all cache for domain"""
        import json
        
        purge = CachePurge(
            domain_id=domain_id,
            purge_type="all",
            initiated_by=initiated_by,
            status="pending"
        )
        
        db.add(purge)
        await db.commit()
        await db.refresh(purge)
        
        # Send purge command to edge nodes via Redis (JSON-serialize dict)
        await redis_client.publish(
            f"cache_purge:{domain_id}",
            json.dumps({"type": "all", "purge_id": purge.id})
        )
        
        return purge
    
    @staticmethod
    async def purge_by_url(
        db: AsyncSession,
        domain_id: int,
        urls: List[str],
        initiated_by: int
    ) -> CachePurge:
        """Purge cache by specific URLs"""
        import json
        
        purge = CachePurge(
            domain_id=domain_id,
            purge_type="url",
            targets=json.dumps(urls),  # JSON-serialize list
            initiated_by=initiated_by,
            status="pending"
        )
        
        db.add(purge)
        await db.commit()
        await db.refresh(purge)
        
        await redis_client.publish(
            f"cache_purge:{domain_id}",
            json.dumps({"type": "url", "urls": urls, "purge_id": purge.id})  # JSON-serialize dict
        )
        
        return purge
    
    @staticmethod
    async def purge_by_pattern(
        db: AsyncSession,
        domain_id: int,
        pattern: str,
        initiated_by: int
    ) -> CachePurge:
        """Purge cache by pattern"""
        import json
        
        purge = CachePurge(
            domain_id=domain_id,
            purge_type="pattern",
            targets=json.dumps([pattern]),  # JSON-serialize list
            initiated_by=initiated_by,
            status="pending"
        )
        
        db.add(purge)
        await db.commit()
        await db.refresh(purge)
        
        await redis_client.publish(
            f"cache_purge:{domain_id}",
            json.dumps({"type": "pattern", "pattern": pattern, "purge_id": purge.id})  # JSON-serialize dict
        )
        
        return purge
    
    @staticmethod
    async def enable_dev_mode(
        db: AsyncSession,
        domain_id: int,
        duration_minutes: int = 10
    ) -> datetime:
        """Enable dev mode (bypass cache) for domain"""
        expires_at = datetime.utcnow() + timedelta(minutes=duration_minutes)
        
        # Store in Redis with TTL
        await redis_client.setex(
            f"dev_mode:{domain_id}",
            duration_minutes * 60,
            expires_at.isoformat()
        )
        
        return expires_at
    
    @staticmethod
    async def disable_dev_mode(db: AsyncSession, domain_id: int) -> bool:
        """Disable dev mode for domain"""
        await redis_client.delete(f"dev_mode:{domain_id}")
        return True
    
    @staticmethod
    async def is_dev_mode_active(db: AsyncSession, domain_id: int) -> bool:
        """Check if dev mode is active"""
        return await redis_client.exists(f"dev_mode:{domain_id}")
    
    @staticmethod
    async def get_dev_mode_expires(
        db: AsyncSession,
        domain_id: int
    ) -> Optional[datetime]:
        """Get dev mode expiration time"""
        expires_str = await redis_client.get(f"dev_mode:{domain_id}")
        if expires_str:
            return datetime.fromisoformat(expires_str)
        return None
    
    @staticmethod
    async def get_purge_history(
        db: AsyncSession,
        domain_id: int,
        limit: int = 50
    ) -> List[CachePurge]:
        """Get cache purge history"""
        query = select(CachePurge).where(
            CachePurge.domain_id == domain_id
        ).order_by(CachePurge.created_at.desc()).limit(limit)
        
        result = await db.execute(query)
        return list(result.scalars().all())
    
    @staticmethod
    async def _trigger_config_update(domain_id: int):
        """Trigger configuration update for edge nodes"""
        import json
        
        # Publish update notification via Redis (JSON-serialize dict)
        await redis_client.publish(
            "config_update",
            json.dumps({"domain_id": domain_id, "timestamp": datetime.utcnow().isoformat()})
        )
