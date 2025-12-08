"""Origin and cache schemas"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum


# Origin schemas
class OriginCreate(BaseModel):
    """Schema for origin creation"""
    name: str = Field(..., min_length=1, max_length=255)
    origin_host: str = Field(..., min_length=1, max_length=255)
    origin_port: int = Field(default=443, ge=1, le=65535)
    protocol: str = Field(default="https", pattern="^(http|https)$")
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
    protocol: Optional[str] = Field(None, pattern="^(http|https)$")
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
    protocol: str
    weight: int
    is_backup: bool
    enabled: bool
    health_status: Optional[str] = "unknown"
    is_healthy: bool = True
    last_health_check: Optional[datetime] = None
    last_check_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
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
    bypass_cookies: Optional[List[str]] = None
    bypass_query_params: Optional[List[str]] = None
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
    bypass_cookies: Optional[List[str]] = None
    bypass_query_params: Optional[List[str]] = None
    cache_by_query_string: Optional[bool] = None
    cache_by_device_type: Optional[bool] = None
    enabled: Optional[bool] = None


class CacheRuleResponse(BaseModel):
    """Schema for cache rule response"""
    id: int
    domain_id: int
    pattern: str
    priority: int
    rule_type: str
    ttl: Optional[int] = None
    respect_origin_headers: bool
    enabled: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class CachePurgeRequest(BaseModel):
    """Schema for cache purge request"""
    purge_type: str = Field(..., pattern="^(all|url|pattern)$")
    urls: Optional[List[str]] = None
    pattern: Optional[str] = None


class CachePurgeResponse(BaseModel):
    """Schema for cache purge response"""
    id: int
    domain_id: int
    purge_type: str
    status: str
    created_at: datetime
    
    class Config:
        from_attributes = True


class DevModeResponse(BaseModel):
    """Schema for dev mode response"""
    enabled: bool
    expires_at: Optional[datetime] = None


# Certificate schemas
class CertificateCreate(BaseModel):
    """Schema for certificate creation"""
    cert_type: str = Field(default="manual", pattern="^(manual|acme)$")
    cert_pem: str = Field(..., min_length=1)
    key_pem: str = Field(..., min_length=1)
    chain_pem: Optional[str] = None


class CertificateUpdate(BaseModel):
    """Schema for certificate update"""
    cert_pem: Optional[str] = Field(None, min_length=1)
    key_pem: Optional[str] = Field(None, min_length=1)
    chain_pem: Optional[str] = None


class CertificateResponse(BaseModel):
    """Schema for certificate response"""
    id: int
    domain_id: int
    cert_type: str = Field(alias="type") # Alias DB field 'type' to 'cert_type'
    status: str
    not_before: Optional[datetime] = None
    not_after: Optional[datetime] = None
    issuer: Optional[str] = None
    subject: Optional[str] = None
    common_name: Optional[str] = None # Added common_name
    created_at: datetime
    
    class Config:
        from_attributes = True
        populate_by_name = True # Allow populating by name or alias


# TLS Settings schemas
class TLSSettingsUpdate(BaseModel):
    """Schema for TLS settings update"""
    mode: Optional[str] = Field(None, pattern="^(flexible|full|strict)$")
    force_https: Optional[bool] = None
    hsts_enabled: Optional[bool] = None
    hsts_max_age: Optional[int] = Field(None, ge=0)
    hsts_include_subdomains: Optional[bool] = None
    hsts_preload: Optional[bool] = None
    min_tls_version: Optional[str] = Field(None, pattern="^(1.0|1.1|1.2|1.3)$")


class TLSSettingsResponse(BaseModel):
    """Schema for TLS settings response"""
    mode: str
    force_https: bool
    hsts_enabled: bool
    hsts_max_age: int
    hsts_include_subdomains: bool
    hsts_preload: bool
    min_tls_version: str



