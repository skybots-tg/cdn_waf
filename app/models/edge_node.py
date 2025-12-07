"""Edge node models"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Float
from sqlalchemy.orm import relationship

from app.core.database import Base


class EdgeNode(Base):
    """Edge node (CDN server) model"""
    __tablename__ = "edge_nodes"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)
    
    # Network
    ip_address = Column(String(45), nullable=False)  # IPv4 or IPv6
    ipv6_address = Column(String(45), nullable=True)
    
    # Location
    location_code = Column(String(20), nullable=False)  # RU-MSK, RU-SPB, etc.
    country_code = Column(String(2), default="RU", nullable=False)
    city = Column(String(100), nullable=True)
    datacenter = Column(String(255), nullable=True)
    
    # Status
    enabled = Column(Boolean, default=True, nullable=False)
    status = Column(String(20), default="unknown", nullable=False)  # online, offline, maintenance
    
    # Health metrics
    last_heartbeat = Column(DateTime, nullable=True)
    cpu_usage = Column(Float, nullable=True)
    memory_usage = Column(Float, nullable=True)
    disk_usage = Column(Float, nullable=True)
    
    # Config version
    config_version = Column(Integer, default=0, nullable=False)
    last_config_update = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


