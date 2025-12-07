"""Domain schemas"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from enum import Enum


class DomainStatusEnum(str, Enum):
    """Domain status enum"""
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class TLSModeEnum(str, Enum):
    """TLS mode enum"""
    FLEXIBLE = "flexible"
    FULL = "full"
    STRICT = "strict"


class DomainCreate(BaseModel):
    """Schema for domain creation"""
    name: str = Field(..., min_length=3, max_length=255)


class DomainUpdate(BaseModel):
    """Schema for domain update"""
    status: Optional[DomainStatusEnum] = None


class DomainResponse(BaseModel):
    """Schema for domain response"""
    id: int
    organization_id: int
    name: str
    status: DomainStatusEnum
    ns_verified: bool
    ns_verified_at: Optional[datetime] = None
    verification_token: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class DomainTLSSettingsUpdate(BaseModel):
    """Schema for TLS settings update"""
    mode: Optional[TLSModeEnum] = None
    force_https: Optional[bool] = None
    hsts_enabled: Optional[bool] = None
    hsts_max_age: Optional[int] = Field(None, ge=0)
    hsts_include_subdomains: Optional[bool] = None
    hsts_preload: Optional[bool] = None
    min_tls_version: Optional[str] = None
    auto_certificate: Optional[bool] = None


class DomainTLSSettingsResponse(BaseModel):
    """Schema for TLS settings response"""
    id: int
    domain_id: int
    mode: TLSModeEnum
    force_https: bool
    hsts_enabled: bool
    hsts_max_age: int
    hsts_include_subdomains: bool
    hsts_preload: bool
    min_tls_version: str
    auto_certificate: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

