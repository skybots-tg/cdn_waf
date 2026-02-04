"""Analytics aggregation models for optimized queries"""
from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, BigInteger, 
    Float, Date, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from datetime import datetime, date

from app.core.database import Base


class HourlyStats(Base):
    """Hourly aggregated statistics per domain"""
    __tablename__ = "analytics_hourly_stats"

    id = Column(Integer, primary_key=True, index=True)
    
    # Time bucket (hour precision)
    hour = Column(DateTime, nullable=False, index=True)
    
    # Domain reference
    domain_id = Column(Integer, ForeignKey("domains.id", ondelete="CASCADE"), nullable=True, index=True)
    domain = relationship("Domain", backref="hourly_stats")
    
    # Edge node reference (optional, for per-node stats)
    edge_node_id = Column(Integer, ForeignKey("edge_nodes.id", ondelete="SET NULL"), nullable=True, index=True)
    edge_node = relationship("EdgeNode", backref="hourly_stats")
    
    # Request metrics
    total_requests = Column(BigInteger, default=0)
    total_bytes_sent = Column(BigInteger, default=0)
    total_bytes_received = Column(BigInteger, default=0)
    
    # Status code distribution
    status_2xx = Column(Integer, default=0)
    status_3xx = Column(Integer, default=0)
    status_4xx = Column(Integer, default=0)
    status_5xx = Column(Integer, default=0)
    
    # Cache metrics
    cache_hits = Column(Integer, default=0)
    cache_misses = Column(Integer, default=0)
    cache_bypass = Column(Integer, default=0)
    
    # WAF metrics
    waf_blocked = Column(Integer, default=0)
    waf_challenged = Column(Integer, default=0)
    
    # Performance (average response time in ms)
    avg_response_time = Column(Float, default=0)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('hour', 'domain_id', 'edge_node_id', name='uq_hourly_stats'),
        Index('ix_hourly_stats_hour_domain', 'hour', 'domain_id'),
    )


class DailyStats(Base):
    """Daily aggregated statistics per domain"""
    __tablename__ = "analytics_daily_stats"

    id = Column(Integer, primary_key=True, index=True)
    
    # Time bucket (day precision)
    day = Column(Date, nullable=False, index=True)
    
    # Domain reference
    domain_id = Column(Integer, ForeignKey("domains.id", ondelete="CASCADE"), nullable=True, index=True)
    domain = relationship("Domain", backref="daily_stats")
    
    # Request metrics
    total_requests = Column(BigInteger, default=0)
    total_bytes_sent = Column(BigInteger, default=0)
    total_bytes_received = Column(BigInteger, default=0)
    
    # Status code distribution
    status_2xx = Column(Integer, default=0)
    status_3xx = Column(Integer, default=0)
    status_4xx = Column(Integer, default=0)
    status_5xx = Column(Integer, default=0)
    
    # Cache metrics
    cache_hits = Column(Integer, default=0)
    cache_misses = Column(Integer, default=0)
    cache_bypass = Column(Integer, default=0)
    
    # WAF metrics
    waf_blocked = Column(Integer, default=0)
    waf_challenged = Column(Integer, default=0)
    
    # Performance
    avg_response_time = Column(Float, default=0)
    
    # Peak metrics (for capacity planning)
    peak_requests_hour = Column(Integer, default=0)  # Max requests in any single hour
    peak_bandwidth_hour = Column(BigInteger, default=0)  # Max bandwidth in any single hour
    
    # Unique visitors approximation (based on unique IPs)
    unique_visitors = Column(Integer, default=0)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('day', 'domain_id', name='uq_daily_stats'),
        Index('ix_daily_stats_day_domain', 'day', 'domain_id'),
    )


class GeoStats(Base):
    """Geographic distribution statistics (daily aggregation)"""
    __tablename__ = "analytics_geo_stats"

    id = Column(Integer, primary_key=True, index=True)
    
    # Time bucket (day precision)
    day = Column(Date, nullable=False, index=True)
    
    # Domain reference
    domain_id = Column(Integer, ForeignKey("domains.id", ondelete="CASCADE"), nullable=True, index=True)
    domain = relationship("Domain", backref="geo_stats")
    
    # Geographic info
    country_code = Column(String(2), nullable=False, index=True)
    
    # Metrics
    total_requests = Column(BigInteger, default=0)
    total_bytes_sent = Column(BigInteger, default=0)
    unique_visitors = Column(Integer, default=0)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('day', 'domain_id', 'country_code', name='uq_geo_stats'),
        Index('ix_geo_stats_day_domain_country', 'day', 'domain_id', 'country_code'),
    )


class TopPathsStats(Base):
    """Top paths statistics (daily aggregation)"""
    __tablename__ = "analytics_top_paths"

    id = Column(Integer, primary_key=True, index=True)
    
    # Time bucket (day precision)
    day = Column(Date, nullable=False, index=True)
    
    # Domain reference
    domain_id = Column(Integer, ForeignKey("domains.id", ondelete="CASCADE"), nullable=False, index=True)
    domain = relationship("Domain", backref="top_paths_stats")
    
    # Path info
    path = Column(String(2048), nullable=False)
    
    # Metrics
    total_requests = Column(BigInteger, default=0)
    total_bytes_sent = Column(BigInteger, default=0)
    
    # Cache performance for this path
    cache_hits = Column(Integer, default=0)
    cache_misses = Column(Integer, default=0)
    
    # Status distribution
    status_2xx = Column(Integer, default=0)
    status_4xx = Column(Integer, default=0)
    status_5xx = Column(Integer, default=0)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('day', 'domain_id', 'path', name='uq_top_paths'),
        Index('ix_top_paths_day_domain', 'day', 'domain_id'),
    )


class ErrorStats(Base):
    """Error tracking statistics (daily aggregation)"""
    __tablename__ = "analytics_error_stats"

    id = Column(Integer, primary_key=True, index=True)
    
    # Time bucket (day precision)
    day = Column(Date, nullable=False, index=True)
    
    # Domain reference
    domain_id = Column(Integer, ForeignKey("domains.id", ondelete="CASCADE"), nullable=False, index=True)
    domain = relationship("Domain", backref="error_stats")
    
    # Error info
    status_code = Column(Integer, nullable=False, index=True)
    path = Column(String(2048), nullable=False)
    
    # Metrics
    error_count = Column(Integer, default=0)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('day', 'domain_id', 'status_code', 'path', name='uq_error_stats'),
        Index('ix_error_stats_day_domain', 'day', 'domain_id'),
    )
