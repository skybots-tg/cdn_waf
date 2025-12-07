"""DNS schemas"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class DNSRecordCreate(BaseModel):
    """Schema for DNS record creation"""
    type: str = Field(..., pattern="^(A|AAAA|CNAME|MX|TXT|SRV|NS|CAA)$")
    name: str = Field(..., max_length=255)
    content: str = Field(..., min_length=1)
    ttl: int = Field(default=3600, ge=60, le=86400)
    priority: Optional[int] = Field(None, ge=0, le=65535)
    weight: Optional[int] = Field(None, ge=0, le=65535)
    proxied: bool = Field(default=False)
    comment: Optional[str] = Field(None, max_length=255)


class DNSRecordImport(BaseModel):
    """Schema for DNS record import"""
    records: List[DNSRecordCreate]


class DNSRecordUpdate(BaseModel):
    """Schema for DNS record update"""
    type: Optional[str] = Field(None, pattern="^(A|AAAA|CNAME|MX|TXT|SRV|NS|CAA)$")
    name: Optional[str] = Field(None, max_length=255)
    content: Optional[str] = None
    ttl: Optional[int] = Field(None, ge=60, le=86400)
    priority: Optional[int] = Field(None, ge=0, le=65535)
    weight: Optional[int] = Field(None, ge=0, le=65535)
    proxied: Optional[bool] = None
    comment: Optional[str] = Field(None, max_length=255)


class DNSRecordResponse(BaseModel):
    """Schema for DNS record response"""
    id: int
    domain_id: int
    type: str
    name: str
    content: str
    ttl: int
    priority: Optional[int] = None
    weight: Optional[int] = None
    proxied: bool
    comment: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True
