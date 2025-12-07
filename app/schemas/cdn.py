"""Origin and cache schemas"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from enum import Enum


# Origin schemas
class OriginCreate(BaseModel):
    """Schema for origin creation"""
    name: str = Field(..., min_length=1, max_length=255)
    origin_host: str = Field(..., min_length=1, max_length=255)
    origin_port: int = Field(default=443, ge=1, le=65535)
    weight: int = Field(default=100, ge=1, le=1000)
    is_backup: bool = Field(default=False)
    enabled: bool = Field(default=True)
    health_check_enabled: bool = Field(default=True)
    health_check_url: str = Field(default="/")
    health_check_interval: int = Field(default=30, ge=10, le=300)
    health_check_timeout: int = Field(default=5, ge=1, le=60)


class OriginUpdate(BaseModel):
    """Schema for origin update"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    origin_host: Optional[str] = Field(None, min_length=1, max_length=255)
    origin_port: Optional[int] = Field(None, ge=1, le=65535)
    weight: Optional[int] = Field(None, ge=1, le=1000)
    is_backup: Optional[bool] = None
    enabled: Optional[bool] = None
    health_check_enabled: Optional[bool] = None
    health_check_url: Optional[str] = None
    health_check_interval: Optional[int] = Field(None, ge=10, le=300)
    health_check_timeout: Optional[int] = Field(None, ge=1, le=60)


class OriginResponse(BaseModel):
    """Schema for origin response"""
    id: int
    domain_id: int
    name: str
    origin_host: str
    origin_port: int
    weight: int
    is_backup: bool
    enabled: bool
    is_healthy: bool
    last_check_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# Cache schemas
class CacheRuleTypeEnum(str, Enum):
    """Cache rule type enum"""
    CACHE = "cache"
    BYPASS = "bypass"
    EDGE_CACHE_TTL = "edge_cache_ttl"


class CacheRuleCreate(BaseModel):
    """Schema for cache rule creation"""
    pattern: str = Field(..., min_length=1, max_length=255)
    priority: int = Field(default=0)
    rule_type: CacheRuleTypeEnum = Field(default=CacheRuleTypeEnum.CACHE)
    ttl: Optional[int] = Field(None, ge=0)
    respect_origin_headers: bool = Field(default=True)
    bypass_cookies: Optional[list[str]] = None
    bypass_query_params: Optional[list[str]] = None
    cache_by_query_string: bool = Field(default=True)
    cache_by_device_type: bool = Field(default=False)
    enabled: bool = Field(default=True)


class CacheRuleUpdate(BaseModel):
    """Schema for cache rule update"""
    pattern: Optional[str] = Field(None, min_length=1, max_length=255)
    priority: Optional[int] = None
    rule_type: Optional[CacheRuleTypeEnum] = None
    ttl: Optional[int] = Field(None, ge=0)
    respect_origin_headers: Optional[bool] = None
    bypass_cookies: Optional[list[str]] = None
    bypass_query_params: Optional[list[str]] = None
    cache_by_query_string: Optional[bool] = None
    cache_by_device_type: Optional[bool] = None
    enabled: Optional[bool] = None


class CacheRuleResponse(BaseModel):
    """Schema for cache rule response"""
    id: int
    domain_id: int
    pattern: str
    priority: int
    rule_type: CacheRuleTypeEnum
    ttl: Optional[int] = None
    respect_origin_headers: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class CachePurgeRequest(BaseModel):
    """Schema for cache purge request"""
    purge_all: bool = Field(default=False)
    urls: Optional[list[str]] = None
    patterns: Optional[list[str]] = None

