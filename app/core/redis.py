"""Redis connection and utilities"""
from typing import Optional
import redis.asyncio as aioredis
from app.core.config import settings


class RedisClient:
    """Redis client wrapper"""
    
    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        self.cache_redis: Optional[aioredis.Redis] = None
    
    async def connect(self):
        """Connect to Redis"""
        self.redis = await aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True
        )
        self.cache_redis = await aioredis.from_url(
            settings.REDIS_URL.replace("/0", f"/{settings.REDIS_CACHE_DB}"),
            encoding="utf-8",
            decode_responses=True
        )
    
    async def disconnect(self):
        """Disconnect from Redis"""
        if self.redis:
            await self.redis.close()
        if self.cache_redis:
            await self.cache_redis.close()
    
    async def get(self, key: str) -> Optional[str]:
        """Get value from Redis"""
        if not self.redis:
            return None
        return await self.redis.get(key)
    
    async def set(self, key: str, value: str, expire: Optional[int] = None):
        """Set value in Redis"""
        if not self.redis:
            return
        await self.redis.set(key, value, ex=expire)
    
    async def setex(self, key: str, time: int, value: str):
        """Set value in Redis with expiration"""
        if not self.redis:
            return
        # Use set with ex parameter which is preferred over setex
        await self.redis.set(key, value, ex=time)

    async def delete(self, key: str):
        """Delete key from Redis"""
        if not self.redis:
            return
        await self.redis.delete(key)
    
    async def exists(self, key: str) -> bool:
        """Check if key exists in Redis"""
        if not self.redis:
            return False
        return await self.redis.exists(key) > 0

    async def publish(self, channel: str, message: str):
        """Publish message to channel"""
        if not self.redis:
            return
        await self.redis.publish(channel, message)


redis_client = RedisClient()
