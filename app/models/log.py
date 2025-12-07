from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, BigInteger
from sqlalchemy.orm import relationship
from datetime import datetime

from app.core.database import Base

class RequestLog(Base):
    __tablename__ = "request_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=True, index=True)
    domain = relationship("Domain", backref="logs")
    
    edge_node_id = Column(Integer, ForeignKey("edge_nodes.id"), nullable=True)
    edge_node = relationship("EdgeNode", backref="logs")
    
    # Request details
    method = Column(String(10))
    path = Column(String(2048))
    query_string = Column(String(2048), nullable=True)
    status_code = Column(Integer)
    bytes_sent = Column(BigInteger)
    
    # Client details
    client_ip = Column(String(45))
    user_agent = Column(String(512), nullable=True)
    referer = Column(String(2048), nullable=True)
    
    # Performance & Security
    request_time = Column(Integer)  # microseconds or milliseconds? let's say milliseconds
    cache_status = Column(String(20)) # HIT, MISS, BYPASS
    waf_status = Column(String(20), nullable=True) # BLOCKED, ALLOWED, CHALLENGED
    waf_rule_id = Column(Integer, nullable=True)
    
    # Geo
    country_code = Column(String(2), nullable=True)

