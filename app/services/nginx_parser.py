"""Nginx configuration parser - extracts settings from nginx config"""
import re
import logging
from typing import Optional, List

from app.schemas.nginx_rules import (
    NginxRulesConfig,
    NginxClientSettings,
    NginxWebSocketSettings,
    NginxProxySettings,
    NginxGzipSettings,
    NginxSSLSettings,
    NginxKeepaliveSettings,
    NginxHttp2Settings,
    NginxSecuritySettings,
    NginxRateLimitSettings,
    NginxCacheSettings
)

logger = logging.getLogger(__name__)


class NginxConfigParser:
    """Parser for nginx configuration files"""
    
    @staticmethod
    def extract_value(config: str, directive: str, default: str = None) -> Optional[str]:
        """Extract directive value from nginx config"""
        pattern = rf'^\s*{directive}\s+([^;]+);'
        match = re.search(pattern, config, re.MULTILINE | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return default
    
    @staticmethod
    def extract_time_value(config: str, directive: str, default: int = 60) -> int:
        """Extract time directive and convert to seconds"""
        value = NginxConfigParser.extract_value(config, directive)
        if not value:
            return default
        
        value = value.lower().strip()
        match = re.match(r'^(\d+)(s|m|h|d)?$', value)
        if match:
            num = int(match.group(1))
            unit = match.group(2) or 's'
            multipliers = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
            return num * multipliers.get(unit, 1)
        
        try:
            return int(value)
        except ValueError:
            return default
    
    @staticmethod
    def parse_config(nginx_config: str) -> NginxRulesConfig:
        """Parse full nginx configuration into NginxRulesConfig"""
        return NginxRulesConfig(
            client=NginxConfigParser.parse_client_settings(nginx_config),
            websocket=NginxConfigParser.parse_websocket_settings(nginx_config),
            proxy=NginxConfigParser.parse_proxy_settings(nginx_config),
            gzip=NginxConfigParser.parse_gzip_settings(nginx_config),
            ssl=NginxConfigParser.parse_ssl_settings(nginx_config),
            rate_limit=NginxConfigParser.parse_rate_limit_settings(nginx_config),
            cache=NginxConfigParser.parse_cache_settings(nginx_config),
            keepalive=NginxConfigParser.parse_keepalive_settings(nginx_config),
            http2=NginxConfigParser.parse_http2_settings(nginx_config),
            security=NginxConfigParser.parse_security_settings(nginx_config)
        )
    
    @staticmethod
    def parse_client_settings(config: str) -> NginxClientSettings:
        """Parse client-related settings"""
        return NginxClientSettings(
            client_max_body_size=NginxConfigParser.extract_value(
                config, 'client_max_body_size', '100m'
            ),
            client_body_timeout=NginxConfigParser.extract_time_value(
                config, 'client_body_timeout', 60
            ),
            client_header_timeout=NginxConfigParser.extract_time_value(
                config, 'client_header_timeout', 60
            ),
            client_body_buffer_size=NginxConfigParser.extract_value(
                config, 'client_body_buffer_size', '128k'
            ),
            large_client_header_buffers=NginxConfigParser.extract_value(
                config, 'large_client_header_buffers', '4 16k'
            )
        )
    
    @staticmethod
    def parse_gzip_settings(config: str) -> NginxGzipSettings:
        """Parse gzip settings"""
        gzip_on = NginxConfigParser.extract_value(config, 'gzip', 'off')
        gzip_level = NginxConfigParser.extract_value(config, 'gzip_comp_level', '6')
        gzip_min = NginxConfigParser.extract_value(config, 'gzip_min_length', '1000')
        gzip_vary = NginxConfigParser.extract_value(config, 'gzip_vary', 'on')
        gzip_types = NginxConfigParser.extract_value(config, 'gzip_types', '')
        
        types_list = gzip_types.split() if gzip_types else [
            "text/plain", "text/css", "text/javascript",
            "application/javascript", "application/json",
            "application/xml", "image/svg+xml"
        ]
        
        return NginxGzipSettings(
            enabled=gzip_on.lower() == 'on',
            comp_level=int(gzip_level) if gzip_level.isdigit() else 6,
            min_length=int(gzip_min) if gzip_min.isdigit() else 1000,
            types=types_list,
            vary=gzip_vary.lower() == 'on'
        )
    
    @staticmethod
    def parse_keepalive_settings(config: str) -> NginxKeepaliveSettings:
        """Parse keepalive settings"""
        timeout = NginxConfigParser.extract_time_value(config, 'keepalive_timeout', 65)
        requests = NginxConfigParser.extract_value(config, 'keepalive_requests', '1000')
        upstream = NginxConfigParser.extract_value(config, 'keepalive', '32')
        
        return NginxKeepaliveSettings(
            timeout=timeout,
            requests=int(requests) if requests.isdigit() else 1000,
            upstream_connections=int(upstream) if upstream.isdigit() else 32
        )
    
    @staticmethod
    def parse_proxy_settings(config: str) -> NginxProxySettings:
        """Parse proxy settings"""
        return NginxProxySettings(
            proxy_connect_timeout=NginxConfigParser.extract_time_value(
                config, 'proxy_connect_timeout', 60
            ),
            proxy_send_timeout=NginxConfigParser.extract_time_value(
                config, 'proxy_send_timeout', 60
            ),
            proxy_read_timeout=NginxConfigParser.extract_time_value(
                config, 'proxy_read_timeout', 60
            ),
            proxy_buffer_size=NginxConfigParser.extract_value(
                config, 'proxy_buffer_size', '4k'
            ),
            proxy_buffers=NginxConfigParser.extract_value(
                config, 'proxy_buffers', '8 4k'
            ),
            proxy_busy_buffers_size=NginxConfigParser.extract_value(
                config, 'proxy_busy_buffers_size', '8k'
            )
        )
    
    @staticmethod
    def parse_ssl_settings(config: str) -> NginxSSLSettings:
        """Parse SSL/TLS settings"""
        protocols_str = NginxConfigParser.extract_value(
            config, 'ssl_protocols', 'TLSv1.2 TLSv1.3'
        )
        protocols = protocols_str.split() if protocols_str else ['TLSv1.2', 'TLSv1.3']
        
        prefer_server = NginxConfigParser.extract_value(
            config, 'ssl_prefer_server_ciphers', 'on'
        )
        session_timeout = NginxConfigParser.extract_value(
            config, 'ssl_session_timeout', '1d'
        )
        session_cache = NginxConfigParser.extract_value(
            config, 'ssl_session_cache', 'shared:SSL:50m'
        )
        stapling = 'ssl_stapling on' in config.lower()
        
        return NginxSSLSettings(
            protocols=protocols,
            prefer_server_ciphers=prefer_server.lower() == 'on',
            session_timeout=session_timeout,
            session_cache=session_cache,
            stapling=stapling
        )
    
    @staticmethod
    def parse_http2_settings(config: str) -> NginxHttp2Settings:
        """Parse HTTP/2 settings"""
        http2_enabled = bool(re.search(r'listen\s+[^;]*\bhttp2\b', config, re.IGNORECASE)) or \
                        NginxConfigParser.extract_value(config, 'http2', 'off').lower() == 'on'
        
        streams = NginxConfigParser.extract_value(
            config, 'http2_max_concurrent_streams', '128'
        )
        field_size = NginxConfigParser.extract_value(
            config, 'http2_max_field_size', '4k'
        )
        header_size = NginxConfigParser.extract_value(
            config, 'http2_max_header_size', '16k'
        )
        
        return NginxHttp2Settings(
            enabled=http2_enabled,
            max_concurrent_streams=int(streams) if streams.isdigit() else 128,
            max_field_size=field_size,
            max_header_size=header_size
        )
    
    @staticmethod
    def parse_security_settings(config: str) -> NginxSecuritySettings:
        """Parse security settings"""
        server_tokens = NginxConfigParser.extract_value(config, 'server_tokens', 'on')
        
        x_frame = 'x-frame-options' in config.lower()
        x_content = 'x-content-type-options' in config.lower()
        x_xss = 'x-xss-protection' in config.lower()
        
        return NginxSecuritySettings(
            server_tokens=server_tokens.lower() == 'on',
            add_x_frame_options=x_frame,
            add_x_content_type_options=x_content,
            add_x_xss_protection=x_xss
        )
    
    @staticmethod
    def parse_rate_limit_settings(config: str) -> NginxRateLimitSettings:
        """Parse rate limiting settings"""
        zone_match = re.search(
            r'limit_req_zone\s+\$\w+\s+zone=(\w+):(\w+)\s+rate=(\w+)',
            config, re.IGNORECASE
        )
        
        if zone_match:
            zone_name = zone_match.group(1)
            zone_size = zone_match.group(2)
            rate = zone_match.group(3)
            
            burst_match = re.search(r'limit_req\s+[^;]*burst=(\d+)', config, re.IGNORECASE)
            burst = int(burst_match.group(1)) if burst_match else 200
            
            nodelay = 'nodelay' in config.lower()
            
            return NginxRateLimitSettings(
                enabled=True,
                zone_name=zone_name,
                zone_size=zone_size,
                rate=rate,
                burst=burst,
                nodelay=nodelay
            )
        
        return NginxRateLimitSettings(enabled=False)
    
    @staticmethod
    def parse_cache_settings(config: str) -> NginxCacheSettings:
        """Parse proxy cache settings"""
        cache_match = re.search(
            r'proxy_cache_path\s+(\S+)\s+.*keys_zone=(\w+):(\w+).*max_size=(\w+)',
            config, re.IGNORECASE
        )
        
        if cache_match:
            path = cache_match.group(1)
            zone_name = cache_match.group(2)
            zone_size = cache_match.group(3)
            max_size = cache_match.group(4)
            
            inactive_match = re.search(r'inactive=(\w+)', config, re.IGNORECASE)
            inactive = inactive_match.group(1) if inactive_match else '7d'
            
            return NginxCacheSettings(
                enabled=True,
                path=path,
                zone_name=zone_name,
                zone_size=zone_size,
                max_size=max_size,
                inactive=inactive
            )
        
        return NginxCacheSettings(enabled=True)  # Default enabled
    
    @staticmethod
    def parse_websocket_settings(config: str) -> NginxWebSocketSettings:
        """Parse WebSocket settings"""
        has_upgrade = 'proxy_set_header upgrade' in config.lower() or \
                      '$http_upgrade' in config.lower()
        has_connection = '$connection_upgrade' in config.lower() or \
                        'proxy_set_header connection' in config.lower()
        
        ws_enabled = has_upgrade and has_connection
        
        return NginxWebSocketSettings(
            enabled=ws_enabled,
            read_timeout=NginxConfigParser.extract_time_value(
                config, 'proxy_read_timeout', 3600
            ) if ws_enabled else 3600,
            send_timeout=NginxConfigParser.extract_time_value(
                config, 'proxy_send_timeout', 3600
            ) if ws_enabled else 3600,
            connect_timeout=NginxConfigParser.extract_time_value(
                config, 'proxy_connect_timeout', 60
            )
        )
