"""Origin and health check models"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Float
from sqlalchemy.orm import relationship

from app.core.database import Base


class Origin(Base):
    """Origin server model"""
    __tablename__ = "origins"
    
    id = Column(Integer, primary_key=True, index=True)
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=False, index=True)
    
    name = Column(String(255), nullable=False)
    origin_host = Column(String(255), nullable=False)  # IP or hostname
    origin_port = Column(Integer, default=443, nullable=False)
    
    # Load balancing
    weight = Column(Integer, default=100, nullable=False)
    is_backup = Column(Boolean, default=False, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    
    # Health check settings
    health_check_enabled = Column(Boolean, default=True, nullable=False)
    health_check_url = Column(String(255), default="/", nullable=False)
    health_check_interval = Column(Integer, default=30, nullable=False)  # seconds
    health_check_timeout = Column(Integer, default=5, nullable=False)  # seconds
    health_check_unhealthy_threshold = Column(Integer, default=3, nullable=False)
    health_check_healthy_threshold = Column(Integer, default=2, nullable=False)
    
    # Current health status
    is_healthy = Column(Boolean, default=True, nullable=False)
    last_check_at = Column(DateTime, nullable=True)
    last_check_duration = Column(Float, nullable=True)  # milliseconds
    consecutive_failures = Column(Integer, default=0, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    domain = relationship("Domain", back_populates="origins")


