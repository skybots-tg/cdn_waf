"""API Token schemas"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class APITokenCreate(BaseModel):
    """Schema for creating API token"""
    name: str = Field(..., min_length=1, max_length=255, description="Token name")
    scopes: Optional[List[str]] = Field(default=None, description="Token permissions")
    allowed_ips: Optional[List[str]] = Field(default=None, description="IP restrictions")
    expires_at: Optional[datetime] = Field(default=None, description="Expiration date")


class APITokenResponse(BaseModel):
    """Schema for API token response (without actual token)"""
    id: int
    user_id: int
    name: str
    key_preview: str  # First 8 chars of token
    scopes: Optional[str] = None
    allowed_ips: Optional[str] = None
    is_active: bool
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class APITokenCreated(BaseModel):
    """Schema for newly created token (includes actual token, shown only once)"""
    id: int
    name: str
    token: str  # Full token, shown only on creation
    key_preview: str
    created_at: datetime

    class Config:
        from_attributes = True
