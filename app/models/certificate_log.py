"""Certificate issuance log models"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Enum as SQLEnum
from sqlalchemy.orm import relationship, backref
import enum

from app.core.database import Base


class CertificateLogLevel(str, enum.Enum):
    """Log level"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"


class CertificateLog(Base):
    """Certificate issuance log model"""
    __tablename__ = "certificate_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    certificate_id = Column(Integer, ForeignKey("certificates.id"), nullable=False, index=True)
    
    level = Column(SQLEnum(CertificateLogLevel), default=CertificateLogLevel.INFO, nullable=False)
    message = Column(Text, nullable=False)
    details = Column(Text, nullable=True)  # JSON with additional details
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    certificate = relationship("Certificate", backref=backref("logs", cascade="all, delete-orphan"))

