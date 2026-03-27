"""Origin server management service"""
import logging
from datetime import datetime
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.origin import Origin
from app.schemas.cdn import OriginCreate, OriginUpdate

logger = logging.getLogger(__name__)


class OriginService:
    """Service for managing origin servers"""
    
    @staticmethod
    async def get_origins(
        db: AsyncSession,
        domain_id: int
    ) -> List[Origin]:
        """Get all origins for domain"""
        query = select(Origin).where(
            Origin.domain_id == domain_id
        ).order_by(Origin.is_backup.asc(), Origin.weight.desc())
        
        result = await db.execute(query)
        return list(result.scalars().all())
    
    @staticmethod
    async def get_origin(db: AsyncSession, origin_id: int) -> Optional[Origin]:
        """Get origin by ID"""
        result = await db.execute(
            select(Origin).where(Origin.id == origin_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def create_origin(
        db: AsyncSession,
        domain_id: int,
        origin_data: OriginCreate
    ) -> Origin:
        """Create new origin server"""
        origin = Origin(
            domain_id=domain_id,
            name=origin_data.name,
            origin_host=origin_data.origin_host,
            origin_port=origin_data.origin_port,
            protocol=origin_data.protocol,
            is_backup=origin_data.is_backup,
            weight=origin_data.weight,
            enabled=origin_data.enabled,
            health_check_enabled=origin_data.health_check_enabled,
            health_check_url=origin_data.health_check_url,
            health_check_interval=origin_data.health_check_interval,
            health_check_timeout=origin_data.health_check_timeout
        )
        
        db.add(origin)
        await db.commit()
        await db.refresh(origin)
        
        return origin
    
    @staticmethod
    async def update_origin(
        db: AsyncSession,
        origin_id: int,
        origin_data: OriginUpdate
    ) -> Optional[Origin]:
        """Update origin server"""
        origin = await OriginService.get_origin(db, origin_id)
        if not origin:
            return None
        
        update_data = origin_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(origin, field):
                setattr(origin, field, value)
        
        await db.commit()
        await db.refresh(origin)
        
        return origin
    
    @staticmethod
    async def delete_origin(db: AsyncSession, origin_id: int) -> bool:
        """Delete origin server"""
        origin = await OriginService.get_origin(db, origin_id)
        if not origin:
            return False
        
        await db.delete(origin)
        await db.commit()
        return True
    
    @staticmethod
    async def check_health(db: AsyncSession, origin_id: int) -> dict:
        """Perform a real HTTP health check against the origin."""
        import httpx
        import time

        origin = await OriginService.get_origin(db, origin_id)
        if not origin:
            return {"status": "error", "message": "Origin not found"}

        url = f"{origin.protocol or 'http'}://{origin.origin_host}:{origin.origin_port}"
        if origin.health_check_url:
            url += origin.health_check_url
        timeout = origin.health_check_timeout or 10

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:
                resp = await client.get(url, timeout=timeout)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            is_healthy = 200 <= resp.status_code < 500
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.warning("Health check failed for origin %s: %s", origin_id, exc)
            is_healthy = False

        await OriginService.update_health_status(db, origin_id, is_healthy, elapsed_ms)

        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "response_time": elapsed_ms,
            "last_check": datetime.utcnow().isoformat(),
        }
    
    @staticmethod
    async def update_health_status(
        db: AsyncSession,
        origin_id: int,
        is_healthy: bool,
        response_time: Optional[int] = None
    ) -> bool:
        """Update origin health status"""
        from datetime import datetime
        
        origin = await OriginService.get_origin(db, origin_id)
        if not origin:
            return False
        
        origin.health_status = "healthy" if is_healthy else "unhealthy"
        origin.is_healthy = is_healthy
        origin.last_health_check = datetime.utcnow()
        origin.last_check_at = datetime.utcnow()
        if response_time is not None:
            origin.last_health_check_response_time = response_time
            origin.last_check_duration = response_time
        
        await db.commit()
        return True
