"""Cache rule models"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class CacheRuleType(str, enum.Enum):
    """Cache rule type"""
    CACHE = "cache"
    BYPASS = "bypass"
    EDGE_CACHE_TTL = "edge_cache_ttl"


class CacheRule(Base):
    """Cache rule model"""
    __tablename__ = "cache_rules"
    
    id = Column(Integer, primary_key=True, index=True)
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=False, index=True)
    
    # Rule matching
    pattern = Column(String(255), nullable=False)  # e.g., /static/*, *.css, *.jpg
    priority = Column(Integer, default=0, nullable=False)  # Higher = evaluated first
    
    rule_type = Column(SQLEnum(CacheRuleType), default=CacheRuleType.CACHE, nullable=False)
    
    # Cache settings
    ttl = Column(Integer, nullable=True)  # seconds, null = respect origin headers
    respect_origin_headers = Column(Boolean, default=True, nullable=False)
    
    # Bypass conditions (JSON)
    bypass_cookies = Column(Text, nullable=True)  # JSON array: ["sessionid", "auth_token"]
    bypass_query_params = Column(Text, nullable=True)  # JSON array: ["nocache", "preview"]
    
    # Cache key customization
    cache_by_query_string = Column(Boolean, default=True, nullable=False)
    cache_by_device_type = Column(Boolean, default=False, nullable=False)
    
    enabled = Column(Boolean, default=True, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    domain = relationship("Domain", back_populates="cache_rules")

