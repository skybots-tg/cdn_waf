"""Nginx rules schemas for edge node configuration"""
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class NginxClientSettings(BaseModel):
    """Client connection settings"""
    client_max_body_size: str = Field(
        default="100m",
        description="Maximum allowed size of the client request body (e.g., 100m, 1g)"
    )
    client_body_timeout: int = Field(
        default=60,
        ge=1, le=3600,
        description="Timeout for reading client request body (seconds)"
    )
    client_header_timeout: int = Field(
        default=60,
        ge=1, le=3600,
        description="Timeout for reading client request header (seconds)"
    )
    client_body_buffer_size: str = Field(
        default="128k",
        description="Buffer size for reading client request body"
    )
    large_client_header_buffers: str = Field(
        default="4 16k",
        description="Number and size of buffers for large client headers"
    )


class NginxWebSocketSettings(BaseModel):
    """WebSocket proxy settings"""
    enabled: bool = Field(
        default=True,
        description="Enable WebSocket protocol support"
    )
    read_timeout: int = Field(
        default=3600,
        ge=1, le=86400,
        description="Proxy read timeout for WebSocket connections (seconds)"
    )
    send_timeout: int = Field(
        default=3600,
        ge=1, le=86400,
        description="Proxy send timeout for WebSocket connections (seconds)"
    )
    connect_timeout: int = Field(
        default=60,
        ge=1, le=300,
        description="Timeout for establishing connection to upstream"
    )


class NginxProxySettings(BaseModel):
    """Proxy settings for backend connections"""
    proxy_connect_timeout: int = Field(
        default=60,
        ge=1, le=300,
        description="Timeout for establishing connection to backend (seconds)"
    )
    proxy_send_timeout: int = Field(
        default=60,
        ge=1, le=3600,
        description="Timeout for transmitting request to backend (seconds)"
    )
    proxy_read_timeout: int = Field(
        default=60,
        ge=1, le=3600,
        description="Timeout for reading response from backend (seconds)"
    )
    proxy_buffer_size: str = Field(
        default="4k",
        description="Size of the buffer for reading first part of response"
    )
    proxy_buffers: str = Field(
        default="8 4k",
        description="Number and size of buffers for reading response"
    )
    proxy_busy_buffers_size: str = Field(
        default="8k",
        description="Maximum size of busy buffers"
    )


class NginxGzipSettings(BaseModel):
    """Gzip compression settings"""
    enabled: bool = Field(
        default=True,
        description="Enable gzip compression"
    )
    comp_level: int = Field(
        default=6,
        ge=1, le=9,
        description="Compression level (1-9, higher = more compression)"
    )
    min_length: int = Field(
        default=1000,
        ge=0,
        description="Minimum response length to compress (bytes)"
    )
    types: List[str] = Field(
        default=[
            "text/plain",
            "text/css",
            "text/javascript",
            "application/javascript",
            "application/json",
            "application/xml",
            "image/svg+xml"
        ],
        description="MIME types to compress"
    )
    vary: bool = Field(
        default=True,
        description="Add Vary: Accept-Encoding header"
    )


class NginxSSLSettings(BaseModel):
    """SSL/TLS settings"""
    protocols: List[str] = Field(
        default=["TLSv1.2", "TLSv1.3"],
        description="Enabled TLS protocols"
    )
    prefer_server_ciphers: bool = Field(
        default=True,
        description="Prefer server ciphers over client ciphers"
    )
    session_timeout: str = Field(
        default="1d",
        description="SSL session cache timeout"
    )
    session_cache: str = Field(
        default="shared:SSL:50m",
        description="SSL session cache configuration"
    )
    stapling: bool = Field(
        default=True,
        description="Enable OCSP stapling"
    )


class NginxRateLimitSettings(BaseModel):
    """Rate limiting settings"""
    enabled: bool = Field(
        default=False,
        description="Enable rate limiting"
    )
    zone_name: str = Field(
        default="cdn_limit",
        description="Name of the rate limit zone"
    )
    zone_size: str = Field(
        default="10m",
        description="Size of the rate limit zone"
    )
    rate: str = Field(
        default="100r/s",
        description="Request rate limit (e.g., 100r/s, 10r/m)"
    )
    burst: int = Field(
        default=200,
        ge=0,
        description="Maximum burst of requests"
    )
    nodelay: bool = Field(
        default=True,
        description="Process burst requests immediately"
    )


class NginxCacheSettings(BaseModel):
    """Proxy cache settings"""
    enabled: bool = Field(
        default=True,
        description="Enable proxy caching"
    )
    path: str = Field(
        default="/var/cache/nginx/cdn",
        description="Path to cache directory"
    )
    zone_name: str = Field(
        default="cdn_cache",
        description="Name of the cache zone"
    )
    zone_size: str = Field(
        default="100m",
        description="Size of cache keys zone"
    )
    max_size: str = Field(
        default="10g",
        description="Maximum size of cache on disk"
    )
    inactive: str = Field(
        default="7d",
        description="Time after which inactive cache is removed"
    )
    use_stale: List[str] = Field(
        default=["error", "timeout", "updating", "http_500", "http_502", "http_503", "http_504"],
        description="Conditions when stale cache can be used"
    )
    valid_codes: Dict[str, str] = Field(
        default={"200": "1d", "301": "1h", "302": "1h", "404": "1m"},
        description="Cache validity per response code"
    )


class NginxKeepaliveSettings(BaseModel):
    """Keepalive connection settings"""
    timeout: int = Field(
        default=65,
        ge=0, le=3600,
        description="Keepalive timeout for client connections (seconds)"
    )
    requests: int = Field(
        default=1000,
        ge=0, le=100000,
        description="Maximum requests per keepalive connection"
    )
    upstream_connections: int = Field(
        default=32,
        ge=0, le=1000,
        description="Number of keepalive connections to upstream"
    )


class NginxHttp2Settings(BaseModel):
    """HTTP/2 settings"""
    enabled: bool = Field(
        default=True,
        description="Enable HTTP/2 protocol"
    )
    max_concurrent_streams: int = Field(
        default=128,
        ge=1, le=1000,
        description="Maximum concurrent streams per connection"
    )
    max_field_size: str = Field(
        default="4k",
        description="Maximum size of a header field"
    )
    max_header_size: str = Field(
        default="16k",
        description="Maximum size of entire header list"
    )


class NginxSecuritySettings(BaseModel):
    """Security headers and settings"""
    server_tokens: bool = Field(
        default=False,
        description="Show nginx version in responses"
    )
    add_x_frame_options: bool = Field(
        default=True,
        description="Add X-Frame-Options: SAMEORIGIN header"
    )
    add_x_content_type_options: bool = Field(
        default=True,
        description="Add X-Content-Type-Options: nosniff header"
    )
    add_x_xss_protection: bool = Field(
        default=True,
        description="Add X-XSS-Protection header"
    )


class NginxRulesConfig(BaseModel):
    """Complete Nginx rules configuration"""
    client: NginxClientSettings = Field(default_factory=NginxClientSettings)
    websocket: NginxWebSocketSettings = Field(default_factory=NginxWebSocketSettings)
    proxy: NginxProxySettings = Field(default_factory=NginxProxySettings)
    gzip: NginxGzipSettings = Field(default_factory=NginxGzipSettings)
    ssl: NginxSSLSettings = Field(default_factory=NginxSSLSettings)
    rate_limit: NginxRateLimitSettings = Field(default_factory=NginxRateLimitSettings)
    cache: NginxCacheSettings = Field(default_factory=NginxCacheSettings)
    keepalive: NginxKeepaliveSettings = Field(default_factory=NginxKeepaliveSettings)
    http2: NginxHttp2Settings = Field(default_factory=NginxHttp2Settings)
    security: NginxSecuritySettings = Field(default_factory=NginxSecuritySettings)


class NginxRulesUpdate(BaseModel):
    """Partial update for Nginx rules"""
    client: Optional[NginxClientSettings] = None
    websocket: Optional[NginxWebSocketSettings] = None
    proxy: Optional[NginxProxySettings] = None
    gzip: Optional[NginxGzipSettings] = None
    ssl: Optional[NginxSSLSettings] = None
    rate_limit: Optional[NginxRateLimitSettings] = None
    cache: Optional[NginxCacheSettings] = None
    keepalive: Optional[NginxKeepaliveSettings] = None
    http2: Optional[NginxHttp2Settings] = None
    security: Optional[NginxSecuritySettings] = None


class NginxRulesResponse(BaseModel):
    """Response with current Nginx rules"""
    node_id: int
    node_name: str
    config: NginxRulesConfig
    last_applied: Optional[str] = None
    status: str = "unknown"


class NginxApplyResult(BaseModel):
    """Result of applying Nginx rules"""
    success: bool
    message: str
    config_test_output: Optional[str] = None
    reload_output: Optional[str] = None
