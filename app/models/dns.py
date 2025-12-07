"""DNS record models"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class DNSRecord(Base):
    """DNS record model"""
    __tablename__ = "dns_records"
    
    id = Column(Integer, primary_key=True, index=True)
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=False, index=True)
    
    # DNS fields
    type = Column(String(10), nullable=False)  # A, AAAA, CNAME, MX, TXT, SRV, NS, CAA
    name = Column(String(255), nullable=False, index=True)  # @ for root, or subdomain
    content = Column(Text, nullable=False)  # IP, hostname, or text content
    ttl = Column(Integer, default=3600, nullable=False)
    
    # Priority for MX, SRV records
    priority = Column(Integer, nullable=True)
    
    # Weight for load balancing
    weight = Column(Integer, nullable=True)
    
    # Proxied through CDN (orange cloud)
    proxied = Column(Boolean, default=False, nullable=False)
    
    # Optional comment
    comment = Column(String(255), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    domain = relationship("Domain", back_populates="dns_records")


