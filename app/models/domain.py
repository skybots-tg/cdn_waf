"""Domain models"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class DomainStatus(str, enum.Enum):
    """Domain verification status"""
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class TLSMode(str, enum.Enum):
    """TLS mode for domain"""
    FLEXIBLE = "flexible"  # Edge to client: HTTPS, Edge to origin: HTTP
    FULL = "full"  # Edge to client: HTTPS, Edge to origin: HTTPS (any cert)
    STRICT = "strict"  # Edge to client: HTTPS, Edge to origin: HTTPS (valid cert)


class Domain(Base):
    """Domain model"""
    __tablename__ = "domains"
    
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    status = Column(SQLEnum(DomainStatus), default=DomainStatus.PENDING, nullable=False)
    
    # Verification
    verification_token = Column(String(64), nullable=True)
    ns_verified = Column(Boolean, default=False, nullable=False)
    ns_verified_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    organization = relationship("Organization", back_populates="domains")
    dns_records = relationship("DNSRecord", back_populates="domain", cascade="all, delete-orphan")
    origins = relationship("Origin", back_populates="domain", cascade="all, delete-orphan")
    tls_settings = relationship("DomainTLSSettings", back_populates="domain", uselist=False, cascade="all, delete-orphan")
    cache_rules = relationship("CacheRule", back_populates="domain", cascade="all, delete-orphan")
    waf_rules = relationship("WAFRule", back_populates="domain", cascade="all, delete-orphan")
    rate_limits = relationship("RateLimit", back_populates="domain", cascade="all, delete-orphan")
    ip_access_rules = relationship("IPAccessRule", back_populates="domain", cascade="all, delete-orphan")
    certificates = relationship("Certificate", back_populates="domain", cascade="all, delete-orphan")


class DomainTLSSettings(Base):
    """TLS/SSL settings for domain"""
    __tablename__ = "domain_tls_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    domain_id = Column(Integer, ForeignKey("domains.id"), unique=True, nullable=False)
    
    mode = Column(SQLEnum(TLSMode), default=TLSMode.FLEXIBLE, nullable=False)
    force_https = Column(Boolean, default=True, nullable=False)  # 301 redirect HTTP to HTTPS
    
    # HSTS
    hsts_enabled = Column(Boolean, default=False, nullable=False)
    hsts_max_age = Column(Integer, default=31536000, nullable=False)  # 1 year
    hsts_include_subdomains = Column(Boolean, default=False, nullable=False)
    hsts_preload = Column(Boolean, default=False, nullable=False)
    
    # TLS versions
    min_tls_version = Column(String(10), default="1.2", nullable=False)
    
    # Certificate settings
    auto_certificate = Column(Boolean, default=True, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    domain = relationship("Domain", back_populates="tls_settings")


