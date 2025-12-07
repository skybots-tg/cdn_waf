"""Edge node schemas"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, IPvAnyAddress, validator


class EdgeNodeBase(BaseModel):
    """Base edge node schema"""
    name: str = Field(..., min_length=1, max_length=255)
    ip_address: str
    ipv6_address: Optional[str] = None
    location_code: str = Field(..., min_length=2, max_length=20)
    country_code: str = Field(default="RU", min_length=2, max_length=2)
    city: Optional[str] = Field(None, max_length=100)
    datacenter: Optional[str] = Field(None, max_length=255)
    enabled: bool = True


class EdgeNodeCreate(EdgeNodeBase):
    """Create edge node schema"""
    ssh_host: Optional[str] = None
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_user: Optional[str] = None
    ssh_key: Optional[str] = None  # SSH private key content
    ssh_password: Optional[str] = None # SSH password


class EdgeNodeUpdate(BaseModel):
    """Update edge node schema"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    ip_address: Optional[str] = None
    ipv6_address: Optional[str] = None
    location_code: Optional[str] = Field(None, min_length=2, max_length=20)
    country_code: Optional[str] = Field(None, min_length=2, max_length=2)
    city: Optional[str] = Field(None, max_length=100)
    datacenter: Optional[str] = Field(None, max_length=255)
    enabled: Optional[bool] = None
    ssh_host: Optional[str] = None
    ssh_port: Optional[int] = Field(None, ge=1, le=65535)
    ssh_user: Optional[str] = None
    ssh_key: Optional[str] = None
    ssh_password: Optional[str] = None


class EdgeNodeResponse(EdgeNodeBase):
    """Edge node response schema"""
    id: int
    status: str
    last_heartbeat: Optional[datetime] = None
    cpu_usage: Optional[float] = None
    memory_usage: Optional[float] = None
    disk_usage: Optional[float] = None
    config_version: int
    last_config_update: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    # SSH info (без приватного ключа и пароля)
    ssh_host: Optional[str] = None
    ssh_port: Optional[int] = None
    ssh_user: Optional[str] = None
    has_ssh_key: bool = False
    has_ssh_password: bool = False

    class Config:
        from_attributes = True


class EdgeNodeStats(BaseModel):
    """Edge node statistics"""
    total_nodes: int
    online_nodes: int
    offline_nodes: int
    maintenance_nodes: int
    total_bandwidth: float  # GB
    total_requests: int


class EdgeNodeCommand(BaseModel):
    """Command to execute on edge node"""
    command: str = Field(..., min_length=1)
    timeout: int = Field(default=30, ge=1, le=300)


class EdgeNodeCommandResult(BaseModel):
    """Result of command execution"""
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    execution_time: float


class EdgeComponentAction(BaseModel):
    """Action for edge node component"""
    component: str = Field(..., description="nginx, redis, certbot, etc.")
    action: str = Field(..., description="start, stop, restart, reload, status, install, update")


class EdgeComponentStatus(BaseModel):
    """Status of edge node component"""
    component: str
    installed: bool
    running: bool
    version: Optional[str] = None
    status_text: str
