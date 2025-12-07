"""WAF and security schemas"""
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class WAFActionEnum(str, Enum):
    """WAF action enum"""
    ALLOW = "allow"
    BLOCK = "block"
    CHALLENGE = "challenge"
    LOG = "log"


class WAFRuleCreate(BaseModel):
    """Schema for WAF rule creation"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    priority: int = Field(default=0)
    action: WAFActionEnum = Field(default=WAFActionEnum.BLOCK)
    conditions: Dict[str, Any] = Field(...)
    enabled: bool = Field(default=True)


class WAFRuleUpdate(BaseModel):
    """Schema for WAF rule update"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    priority: Optional[int] = None
    action: Optional[WAFActionEnum] = None
    conditions: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class WAFRuleResponse(BaseModel):
    """Schema for WAF rule response"""
    id: int
    domain_id: int
    name: str
    description: Optional[str] = None
    priority: int
    action: WAFActionEnum
    conditions: Dict[str, Any]
    enabled: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class RateLimitCreate(BaseModel):
    """Schema for rate limit creation"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    key_type: str = Field(default="ip")
    custom_key: Optional[str] = None
    path_pattern: Optional[str] = None
    limit: int = Field(..., ge=1)
    interval: int = Field(..., ge=1)
    action: str = Field(default="block")
    block_duration: int = Field(default=300, ge=1)
    response_status: int = Field(default=429)
    response_body: Optional[str] = None
    enabled: bool = Field(default=True)


class RateLimitUpdate(BaseModel):
    """Schema for rate limit update"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    key_type: Optional[str] = None
    custom_key: Optional[str] = None
    path_pattern: Optional[str] = None
    limit: Optional[int] = Field(None, ge=1)
    interval: Optional[int] = Field(None, ge=1)
    action: Optional[str] = None
    block_duration: Optional[int] = Field(None, ge=1)
    response_status: Optional[int] = None
    response_body: Optional[str] = None
    enabled: Optional[bool] = None


class RateLimitResponse(BaseModel):
    """Schema for rate limit response"""
    id: int
    domain_id: int
    name: str
    description: Optional[str] = None
    key_type: str
    path_pattern: Optional[str] = None
    limit: int
    interval: int
    action: str
    block_duration: int
    response_status: int
    enabled: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

