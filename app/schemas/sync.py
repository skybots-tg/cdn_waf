from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field

class UserSync(BaseModel):
    id: int
    email: str
    password_hash: str
    full_name: Optional[str] = None
    is_active: bool
    is_superuser: bool
    totp_secret: Optional[str] = None
    totp_enabled: bool = False
    last_login: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

class OrganizationSync(BaseModel):
    id: int
    name: str
    owner_id: int
    created_at: datetime
    updated_at: datetime

class DomainSync(BaseModel):
    id: int
    organization_id: int
    name: str
    status: str
    verification_token: Optional[str] = None
    ns_verified: bool
    ns_verified_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

class DNSRecordSync(BaseModel):
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

class EdgeNodeSync(BaseModel):
    id: int
    name: str
    ip_address: str
    ipv6_address: Optional[str] = None
    location_code: str
    country_code: str
    city: Optional[str] = None
    datacenter: Optional[str] = None
    enabled: bool
    status: str
    created_at: datetime
    updated_at: datetime

class DNSSyncPayload(BaseModel):
    users: List[UserSync]
    organizations: List[OrganizationSync]
    domains: List[DomainSync]
    records: List[DNSRecordSync]
    edge_nodes: List[EdgeNodeSync]
