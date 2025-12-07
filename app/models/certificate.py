"""Certificate models"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Enum as SQLEnum, Boolean
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class CertificateType(str, enum.Enum):
    """Certificate type"""
    ACME = "acme"  # Let's Encrypt
    MANUAL = "manual"  # User uploaded


class CertificateStatus(str, enum.Enum):
    """Certificate status"""
    PENDING = "pending"
    ISSUED = "issued"
    EXPIRED = "expired"
    REVOKED = "revoked"


class Certificate(Base):
    """SSL/TLS certificate model"""
    __tablename__ = "certificates"
    
    id = Column(Integer, primary_key=True, index=True)
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=False, index=True)
    
    type = Column(SQLEnum(CertificateType), default=CertificateType.ACME, nullable=False)
    status = Column(SQLEnum(CertificateStatus), default=CertificateStatus.PENDING, nullable=False)
    
    # Certificate details
    common_name = Column(String(255), nullable=False)
    san = Column(Text, nullable=True)  # JSON array of Subject Alternative Names
    issuer = Column(String(500), nullable=True)
    subject = Column(String(500), nullable=True)
    
    # Validity
    not_before = Column(DateTime, nullable=True)
    not_after = Column(DateTime, nullable=True)
    
    # Certificate data (encrypted in production)
    cert_pem = Column(Text, nullable=True)
    key_pem = Column(Text, nullable=True)  # Should be encrypted!
    chain_pem = Column(Text, nullable=True)
    
    # ACME specific
    acme_order_url = Column(String(512), nullable=True)
    acme_account_key = Column(Text, nullable=True)  # Should be encrypted!
    acme_challenge_type = Column(String(20), nullable=True)  # http-01, dns-01
    
    # Auto-renewal
    auto_renew = Column(Boolean, default=True, nullable=False)
    renew_before_days = Column(Integer, default=30, nullable=False)
    last_renewed_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    domain = relationship("Domain", back_populates="certificates")


