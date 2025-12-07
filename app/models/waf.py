"""WAF and security rule models"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class WAFAction(str, enum.Enum):
    """WAF rule action"""
    ALLOW = "allow"
    BLOCK = "block"
    CHALLENGE = "challenge"
    LOG = "log"


class WAFRule(Base):
    """WAF rule model"""
    __tablename__ = "waf_rules"
    
    id = Column(Integer, primary_key=True, index=True)
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=False, index=True)
    
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    priority = Column(Integer, default=0, nullable=False)
    action = Column(SQLEnum(WAFAction), default=WAFAction.BLOCK, nullable=False)
    
    # Conditions (stored as JSON)
    # Example: {"path": "/admin/*", "method": ["POST", "DELETE"], "ip_range": "192.168.0.0/16"}
    conditions = Column(Text, nullable=False)  # JSON
    
    enabled = Column(Boolean, default=True, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    domain = relationship("Domain", back_populates="waf_rules")


class RateLimit(Base):
    """Rate limiting rule model"""
    __tablename__ = "rate_limits"
    
    id = Column(Integer, primary_key=True, index=True)
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=False, index=True)
    
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Rate limit key type
    key_type = Column(String(50), default="ip", nullable=False)  # ip, ip_path, custom
    custom_key = Column(String(255), nullable=True)  # For custom rate limiting
    
    # Path pattern to match
    path_pattern = Column(String(255), nullable=True)  # e.g., /api/*, null = all paths
    
    # Limits
    limit = Column(Integer, nullable=False)  # Number of requests
    interval = Column(Integer, nullable=False)  # Time window in seconds
    
    # Action when limit exceeded
    action = Column(String(20), default="block", nullable=False)  # block, throttle
    block_duration = Column(Integer, default=300, nullable=False)  # seconds
    
    # HTTP response
    response_status = Column(Integer, default=429, nullable=False)
    response_body = Column(Text, nullable=True)
    
    enabled = Column(Boolean, default=True, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    domain = relationship("Domain", back_populates="rate_limits")


