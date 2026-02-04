"""Nginx configuration management service"""
import logging
import json
import os
import tempfile
from typing import Optional, Dict, Any
from datetime import datetime

from app.models.edge_node import EdgeNode
from app.schemas.nginx_rules import (
    NginxRulesConfig,
    NginxRulesUpdate,
    NginxApplyResult
)
from app.services.edge_service import EdgeNodeService
from app.services.nginx_parser import NginxConfigParser

logger = logging.getLogger(__name__)

# Remote path for storing nginx rules config
NGINX_RULES_CONFIG_PATH = "/opt/cdn_waf/nginx_rules.json"
NGINX_CONF_D_PATH = "/etc/nginx/conf.d"
NGINX_RULES_CONF_PATH = f"{NGINX_CONF_D_PATH}/00-cdn-rules.conf"


class NginxRulesService:
    """Service for managing Nginx rules on edge nodes"""
    
    @staticmethod
    async def get_rules(node: EdgeNode) -> NginxRulesConfig:
        """Get current Nginx rules from edge node"""
        # Try to read our saved config first
        result = await EdgeNodeService.execute_command(
            node,
            f"cat {NGINX_RULES_CONFIG_PATH} 2>/dev/null || echo ''"
        )
        
        if result.success and result.stdout.strip():
            try:
                data = json.loads(result.stdout.strip())
                if data:  # If we have saved config, use it
                    return NginxRulesConfig(**data)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Failed to parse saved nginx rules config: {e}")
        
        # No saved config - parse real nginx configuration
        return await NginxRulesService.parse_nginx_config(node)
    
    @staticmethod
    async def parse_nginx_config(node: EdgeNode) -> NginxRulesConfig:
        """Parse real nginx configuration from the edge node"""
        # Get nginx full config dump
        cmd = "nginx -T 2>/dev/null || cat /etc/nginx/nginx.conf /etc/nginx/conf.d/*.conf 2>/dev/null || echo ''"
        result = await EdgeNodeService.execute_command(node, cmd, timeout=30)
        
        if not result.success or not result.stdout.strip():
            logger.warning(f"Could not read nginx config from {node.name}")
            return NginxRulesConfig()
        
        # Use parser to extract settings
        return NginxConfigParser.parse_config(result.stdout)
    
    @staticmethod
    def generate_nginx_config(config: NginxRulesConfig) -> str:
        """Generate nginx configuration from rules"""
        lines = [
            "# CDN WAF Nginx Rules Configuration",
            "# Auto-generated - do not edit manually",
            f"# Generated at: {datetime.utcnow().isoformat()}",
            "",
        ]
        
        # Client settings
        lines.extend([
            "# === Client Settings ===",
            f"client_max_body_size {config.client.client_max_body_size};",
            f"client_body_timeout {config.client.client_body_timeout}s;",
            f"client_header_timeout {config.client.client_header_timeout}s;",
            f"client_body_buffer_size {config.client.client_body_buffer_size};",
            f"large_client_header_buffers {config.client.large_client_header_buffers};",
            "",
        ])
        
        # Keepalive settings
        lines.extend([
            "# === Keepalive Settings ===",
            f"keepalive_timeout {config.keepalive.timeout}s;",
            f"keepalive_requests {config.keepalive.requests};",
            "",
        ])
        
        # Gzip settings
        if config.gzip.enabled:
            gzip_types = " ".join(config.gzip.types)
            lines.extend([
                "# === Gzip Compression ===",
                "gzip on;",
                f"gzip_comp_level {config.gzip.comp_level};",
                f"gzip_min_length {config.gzip.min_length};",
                f"gzip_types {gzip_types};",
                f"gzip_vary {'on' if config.gzip.vary else 'off'};",
                "gzip_proxied any;",
                "",
            ])
        else:
            lines.extend([
                "# === Gzip Compression (disabled) ===",
                "gzip off;",
                "",
            ])
        
        # SSL settings
        # Deduplicate protocols while preserving order
        seen = set()
        unique_protocols = []
        for p in config.ssl.protocols:
            if p not in seen:
                seen.add(p)
                unique_protocols.append(p)
        protocols = " ".join(unique_protocols)
        lines.extend([
            "# === SSL/TLS Settings ===",
            f"ssl_protocols {protocols};",
            f"ssl_prefer_server_ciphers {'on' if config.ssl.prefer_server_ciphers else 'off'};",
            f"ssl_session_timeout {config.ssl.session_timeout};",
            f"ssl_session_cache {config.ssl.session_cache};",
        ])
        if config.ssl.stapling:
            lines.extend([
                "ssl_stapling on;",
                "ssl_stapling_verify on;",
            ])
        lines.append("")
        
        # Security settings
        lines.extend([
            "# === Security Settings ===",
            f"server_tokens {'on' if config.security.server_tokens else 'off'};",
        ])
        if config.security.add_x_frame_options:
            lines.append('add_header X-Frame-Options "SAMEORIGIN" always;')
        if config.security.add_x_content_type_options:
            lines.append('add_header X-Content-Type-Options "nosniff" always;')
        if config.security.add_x_xss_protection:
            lines.append('add_header X-XSS-Protection "1; mode=block" always;')
        lines.append("")
        
        # HTTP/2 settings
        if config.http2.enabled:
            lines.extend([
                "# === HTTP/2 Settings ===",
                f"http2_max_concurrent_streams {config.http2.max_concurrent_streams};",
                f"http2_max_field_size {config.http2.max_field_size};",
                f"http2_max_header_size {config.http2.max_header_size};",
                "",
            ])
        
        # Rate limiting zone (if enabled)
        if config.rate_limit.enabled:
            lines.extend([
                "# === Rate Limiting ===",
                f"limit_req_zone $binary_remote_addr zone={config.rate_limit.zone_name}:{config.rate_limit.zone_size} rate={config.rate_limit.rate};",
                "",
            ])
        
        # Proxy cache zone (if enabled)
        if config.cache.enabled:
            use_stale = " ".join(config.cache.use_stale)
            lines.extend([
                "# === Proxy Cache ===",
                f"proxy_cache_path {config.cache.path} levels=1:2 keys_zone={config.cache.zone_name}:{config.cache.zone_size} max_size={config.cache.max_size} inactive={config.cache.inactive};",
                "",
            ])
        
        return "\n".join(lines)
    
    @staticmethod
    def generate_location_snippet(config: NginxRulesConfig) -> str:
        """Generate nginx location block snippet for including in server blocks"""
        lines = [
            "# CDN WAF Location Rules (include this in your location blocks)",
            "",
        ]
        
        # Proxy settings
        lines.extend([
            "# Proxy timeouts",
            f"proxy_connect_timeout {config.proxy.proxy_connect_timeout}s;",
            f"proxy_send_timeout {config.proxy.proxy_send_timeout}s;",
            f"proxy_read_timeout {config.proxy.proxy_read_timeout}s;",
            "",
            "# Proxy buffers",
            f"proxy_buffer_size {config.proxy.proxy_buffer_size};",
            f"proxy_buffers {config.proxy.proxy_buffers};",
            f"proxy_busy_buffers_size {config.proxy.proxy_busy_buffers_size};",
            "",
        ])
        
        # WebSocket support
        if config.websocket.enabled:
            lines.extend([
                "# WebSocket support",
                "proxy_http_version 1.1;",
                'proxy_set_header Upgrade $http_upgrade;',
                'proxy_set_header Connection $connection_upgrade;',
                f"proxy_read_timeout {config.websocket.read_timeout}s;",
                f"proxy_send_timeout {config.websocket.send_timeout}s;",
                "",
            ])
        
        # Rate limiting in location
        if config.rate_limit.enabled:
            nodelay = " nodelay" if config.rate_limit.nodelay else ""
            lines.extend([
                "# Rate limiting",
                f"limit_req zone={config.rate_limit.zone_name} burst={config.rate_limit.burst}{nodelay};",
                "",
            ])
        
        # Caching in location
        if config.cache.enabled:
            lines.extend([
                "# Proxy cache",
                f"proxy_cache {config.cache.zone_name};",
                "proxy_cache_key $scheme$request_method$host$request_uri;",
            ])
            for code, validity in config.cache.valid_codes.items():
                lines.append(f"proxy_cache_valid {code} {validity};")
            use_stale = " ".join(config.cache.use_stale)
            lines.append(f"proxy_cache_use_stale {use_stale};")
            lines.append("")
        
        return "\n".join(lines)
    
    @staticmethod
    async def apply_rules(
        node: EdgeNode,
        config: NginxRulesConfig,
        test_only: bool = False
    ) -> NginxApplyResult:
        """Apply Nginx rules to edge node"""
        try:
            # Generate config content
            nginx_config = NginxRulesService.generate_nginx_config(config)
            location_snippet = NginxRulesService.generate_location_snippet(config)
            config_json = config.model_dump_json(indent=2)
            
            # Comment out conflicting directives in nginx.conf to avoid duplicates
            # These directives will be managed by our 00-cdn-rules.conf
            conflict_directives = [
                'gzip', 'gzip_comp_level', 'gzip_min_length', 'gzip_types', 
                'gzip_vary', 'gzip_proxied', 'gzip_disable',
                'client_max_body_size', 'client_body_timeout', 'client_header_timeout',
                'client_body_buffer_size', 'large_client_header_buffers',
                'keepalive_timeout', 'keepalive_requests',
                'server_tokens',
                'ssl_protocols', 'ssl_prefer_server_ciphers', 'ssl_session_timeout',
                'ssl_session_cache', 'ssl_stapling', 'ssl_stapling_verify',
                'ssl_ciphers', 'ssl_ecdh_curve'
            ]
            
            # Build sed command to comment out conflicting directives
            sed_patterns = ' '.join([
                f"-e 's/^[[:space:]]*{d}[[:space:]]/#cdn_waf_managed# &/'"
                for d in conflict_directives
            ])
            
            # Backup and modify nginx.conf
            backup_cmd = (
                f"cp -n /etc/nginx/nginx.conf /etc/nginx/nginx.conf.cdn_waf_backup 2>/dev/null || true; "
                f"sed -i {sed_patterns} /etc/nginx/nginx.conf"
            )
            await EdgeNodeService.execute_command(node, backup_cmd, timeout=30)
            
            # Create temporary files
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.conf') as f:
                f.write(nginx_config)
                tmp_nginx_conf = f.name
            
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
                f.write(config_json)
                tmp_json = f.name
            
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.conf') as f:
                f.write(location_snippet)
                tmp_location = f.name
            
            try:
                # Upload files
                upload_success = await EdgeNodeService.upload_file(
                    node, tmp_nginx_conf, NGINX_RULES_CONF_PATH
                )
                if not upload_success:
                    return NginxApplyResult(
                        success=False,
                        message="Failed to upload nginx config file"
                    )
                
                upload_success = await EdgeNodeService.upload_file(
                    node, tmp_json, NGINX_RULES_CONFIG_PATH
                )
                if not upload_success:
                    return NginxApplyResult(
                        success=False,
                        message="Failed to upload config JSON file"
                    )
                
                # Upload location snippet for reference
                await EdgeNodeService.upload_file(
                    node, tmp_location, "/opt/cdn_waf/nginx_location_rules.conf"
                )
                
            finally:
                # Cleanup temp files
                os.unlink(tmp_nginx_conf)
                os.unlink(tmp_json)
                os.unlink(tmp_location)
            
            # Test nginx configuration
            test_result = await EdgeNodeService.execute_command(
                node, "nginx -t 2>&1"
            )
            
            if not test_result.success:
                return NginxApplyResult(
                    success=False,
                    message="Nginx configuration test failed",
                    config_test_output=test_result.stdout + test_result.stderr
                )
            
            if test_only:
                return NginxApplyResult(
                    success=True,
                    message="Configuration test passed",
                    config_test_output=test_result.stdout + test_result.stderr
                )
            
            # Reload nginx
            reload_result = await EdgeNodeService.execute_command(
                node, "nginx -s reload 2>&1 || systemctl reload nginx 2>&1"
            )
            
            if not reload_result.success:
                return NginxApplyResult(
                    success=False,
                    message="Nginx reload failed",
                    config_test_output=test_result.stdout + test_result.stderr,
                    reload_output=reload_result.stdout + reload_result.stderr
                )
            
            return NginxApplyResult(
                success=True,
                message="Nginx rules applied successfully",
                config_test_output=test_result.stdout + test_result.stderr,
                reload_output=reload_result.stdout + reload_result.stderr
            )
            
        except Exception as e:
            logger.error(f"Failed to apply nginx rules to node {node.name}: {e}")
            return NginxApplyResult(
                success=False,
                message=f"Error applying rules: {str(e)}"
            )
    
    @staticmethod
    async def get_nginx_status(node: EdgeNode) -> Dict[str, Any]:
        """Get current nginx status from edge node"""
        result = await EdgeNodeService.execute_command(
            node,
            "nginx -v 2>&1; systemctl is-active nginx; nginx -t 2>&1"
        )
        
        lines = (result.stdout + result.stderr).strip().split('\n')
        
        version = None
        is_active = False
        config_valid = False
        
        for line in lines:
            if 'nginx version:' in line or 'nginx/' in line:
                version = line.split('/')[-1].strip() if '/' in line else line
            elif line.strip() == 'active':
                is_active = True
            elif 'syntax is ok' in line.lower() or 'test is successful' in line.lower():
                config_valid = True
        
        return {
            "version": version,
            "is_active": is_active,
            "config_valid": config_valid,
            "raw_output": result.stdout + result.stderr
        }
