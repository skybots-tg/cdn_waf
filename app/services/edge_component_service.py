"""Edge node component management (install, status, configure)."""
import logging
import os
import tempfile
from typing import Optional, Dict, Any

from app.models.edge_node import EdgeNode
from app.schemas.edge_node import EdgeNodeCommandResult, EdgeComponentStatus
from app.core.config import settings

logger = logging.getLogger(__name__)


class EdgeComponentService:
    """Manages components (nginx, redis, agent, geoip, ...) on edge nodes."""

    @staticmethod
    async def get_component_status(node: EdgeNode, component: str) -> EdgeComponentStatus:
        """Get status of component on edge node"""
        from app.services.edge_service import EdgeNodeService

        if component == "system":
            cmd = "which curl && which git"
            result = await EdgeNodeService.execute_command(node, cmd)
            return EdgeComponentStatus(
                component=component, installed=result.success,
                running=True, version=None,
                status_text="Installed" if result.success else "Not installed",
            )

        if component == "python":
            cmd = "[ -f /opt/cdn_waf/venv/bin/python ] && echo 'exists'"
            result = await EdgeNodeService.execute_command(node, cmd)
            return EdgeComponentStatus(
                component=component, installed=result.success,
                running=True, version=None,
                status_text="Active" if result.success else "Missing venv",
            )

        if component == "certbot":
            cmd = "certbot --version"
            result = await EdgeNodeService.execute_command(node, cmd)
            installed = result.success
            version = None
            if installed and result.stdout:
                parts = result.stdout.strip().split()
                if len(parts) >= 2:
                    version = parts[1]
            return EdgeComponentStatus(
                component=component, installed=installed,
                running=installed, version=version,
                status_text="Ready" if installed else "Not installed",
            )

        if component == "geoip":
            db_check = await EdgeNodeService.execute_command(
                node, "ls /usr/share/GeoIP/GeoLite2-Country.mmdb 2>/dev/null"
            )
            version_check = await EdgeNodeService.execute_command(
                node, "geoipupdate --version 2>/dev/null | head -1"
            )
            installed = db_check.success
            version = None
            if version_check.success and version_check.stdout:
                parts = version_check.stdout.strip().split()
                if len(parts) >= 2:
                    version = parts[1]
            status_text = "Ready" if installed else "Database not found"
            if not version_check.success:
                status_text = "geoipupdate not installed"
            return EdgeComponentStatus(
                component=component,
                installed=installed or version_check.success,
                running=installed, version=version, status_text=status_text,
            )

        service_name = component
        if component == "agent":
            service_name = "cdn-waf-agent"

        cmd = f"systemctl is-active {service_name}"
        result = await EdgeNodeService.execute_command(node, cmd)
        status_output = result.stdout.strip()
        running = status_output == "active"

        if not result.success:
            if "SSH" in result.stderr:
                status_text = "Connection Error"
            elif status_output:
                status_text = status_output
            else:
                status_text = "Stopped"
        elif status_output:
            status_text = status_output
        else:
            status_text = "unknown"

        version = None
        if running:
            version_cmd = ""
            if component == "nginx":
                version_cmd = "nginx -v 2>&1 | cut -d '/' -f 2"
            elif component == "redis":
                version_cmd = "redis-server -v | awk '{print $3}' | cut -d= -f2"
            if version_cmd:
                v_res = await EdgeNodeService.execute_command(node, version_cmd)
                if v_res.success:
                    version = v_res.stdout.strip()

        installed = running
        if not installed:
            check_cmd = f"command -v {component}"
            if component == "redis":
                check_cmd = "command -v redis-server"
            elif component == "agent":
                check_cmd = "systemctl list-unit-files | grep cdn-waf-agent"
            c_res = await EdgeNodeService.execute_command(node, check_cmd)
            installed = c_res.success

        return EdgeComponentStatus(
            component=component, installed=installed,
            running=running, version=version, status_text=status_text,
        )

    @staticmethod
    async def run_setup_script(node: EdgeNode, action_name: str) -> EdgeNodeCommandResult:
        """Run setup script action on node"""
        from app.services.edge_service import EdgeNodeService

        setup_script = "edge_node/setup.sh"
        if not os.path.exists(setup_script):
            return EdgeNodeCommandResult(
                success=False, stdout="",
                stderr=f"Setup script not found: {setup_script}",
                exit_code=1, execution_time=0,
            )

        if not await EdgeNodeService.upload_file(node, setup_script, "/tmp/setup.sh"):
            return EdgeNodeCommandResult(
                success=False, stdout="",
                stderr="Failed to upload setup script",
                exit_code=1, execution_time=0,
            )

        await EdgeNodeService.execute_command(node, "chmod +x /tmp/setup.sh")
        cmd = f"/tmp/setup.sh {action_name}"
        return await EdgeNodeService.execute_command(node, cmd, timeout=300)

    @staticmethod
    async def manage_component(
        node: EdgeNode,
        component: str,
        action: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> EdgeNodeCommandResult:
        """Manage component on edge node (start, stop, restart, install, etc.)"""
        from app.services.edge_service import EdgeNodeService

        if action == "install" or (component == "agent" and action == "update"):
            return await EdgeComponentService._handle_install(node, component, action, params)

        if component == "python" and action == "update":
            await EdgeNodeService.execute_command(node, "mkdir -p /opt/cdn_waf")
            if not await EdgeNodeService.upload_file(
                node, "edge_node/requirements.txt", "/opt/cdn_waf/requirements.txt"
            ):
                return EdgeNodeCommandResult(
                    success=False, stdout="",
                    stderr="Failed to upload requirements.txt",
                    exit_code=1, execution_time=0,
                )

        command_map = {
            "nginx": {
                "start": "systemctl start nginx || systemctl start openresty",
                "stop": "systemctl stop nginx || systemctl stop openresty",
                "restart": "systemctl restart nginx || systemctl restart openresty",
                "reload": "nginx -s reload || openresty -s reload",
                "status": "systemctl status nginx || systemctl status openresty",
                "update": "apt-get update && apt-get upgrade -y nginx openresty",
            },
            "redis": {
                "start": "systemctl start redis-server",
                "stop": "systemctl stop redis-server",
                "restart": "systemctl restart redis-server",
                "status": "systemctl status redis-server",
                "install": "apt-get update && apt-get install -y redis-server",
            },
            "certbot": {
                "install": "apt-get update && apt-get install -y certbot python3-certbot-nginx",
                "status": "certbot --version",
            },
            "geoip": {
                "status": "ls -la /usr/share/GeoIP/*.mmdb 2>/dev/null && geoipupdate --version 2>/dev/null || echo 'GeoIP not installed'",
                "update": "geoipupdate -v",
            },
            "system": {
                "install": (
                    "apt-get update && apt-get install -y curl git build-essential python3-dev python3-pip ca-certificates "
                    "&& PYVER=$(python3 -c 'import sys; print(f\"{sys.version_info.major}.{sys.version_info.minor}\")' 2>/dev/null || echo '3') "
                    "&& apt-get install -y python${PYVER}-venv || apt-get install -y python3-venv"
                ),
            },
            "python": {
                "update": "cd /opt/cdn_waf && ./venv/bin/pip install --upgrade pip && ./venv/bin/pip install -r requirements.txt",
            },
            "agent": {
                "start": "systemctl start cdn-waf-agent",
                "stop": "systemctl stop cdn-waf-agent",
                "restart": "systemctl restart cdn-waf-agent",
                "status": "systemctl status cdn-waf-agent",
            },
        }

        if component not in command_map or action not in command_map[component]:
            return EdgeNodeCommandResult(
                success=False, stdout="",
                stderr=f"Unknown component '{component}' or action '{action}'",
                exit_code=1, execution_time=0.0,
            )

        return await EdgeNodeService.execute_command(node, command_map[component][action])

    @staticmethod
    async def _handle_install(
        node: EdgeNode, component: str, action: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> EdgeNodeCommandResult:
        """Dispatch install / agent-update."""
        from app.services.edge_service import EdgeNodeService

        if component == "system":
            return await EdgeComponentService.run_setup_script(node, "install_deps")
        if component == "nginx":
            return await EdgeComponentService.run_setup_script(node, "install_nginx")
        if component == "certbot":
            return await EdgeComponentService.run_setup_script(node, "install_certbot")
        if component == "geoip":
            result = await EdgeComponentService.run_setup_script(node, "install_geoip")
            if result.success:
                await EdgeComponentService.configure_geoip(node)
            return result
        if component == "python":
            await EdgeNodeService.execute_command(node, "mkdir -p /opt/cdn_waf")
            if not await EdgeNodeService.upload_file(
                node, "edge_node/requirements.txt", "/opt/cdn_waf/requirements.txt"
            ):
                return EdgeNodeCommandResult(
                    success=False, stdout="",
                    stderr="Failed to upload requirements.txt",
                    exit_code=1, execution_time=0,
                )
            return await EdgeComponentService.run_setup_script(node, "install_python")

        if component == "agent":
            return await EdgeComponentService._install_agent(node, action, params)

        return EdgeNodeCommandResult(
            success=False, stdout="",
            stderr=f"Unknown component for install: {component}",
            exit_code=1, execution_time=0,
        )

    @staticmethod
    async def _install_agent(
        node: EdgeNode, action: str, params: Optional[Dict[str, Any]] = None
    ) -> EdgeNodeCommandResult:
        from app.services.edge_service import EdgeNodeService

        update_config = action != "update"

        files_to_upload = [
            ("edge_node/edge_config_updater.py", "/opt/cdn_waf/edge_config_updater.py"),
            ("edge_node/requirements.txt", "/opt/cdn_waf/requirements.txt"),
        ]
        tmp_config_path = None

        if update_config:
            with open("edge_node/config.example.yaml", "r") as f:
                config_content = f.read()

            config_content = config_content.replace("id: 1", f"id: {node.id}")
            config_content = config_content.replace('name: "ru-msk-01"', f'name: "{node.name}"')
            config_content = config_content.replace('location: "RU-MSK"', f'location: "{node.location_code}"')

            control_plane_url = (params.get("control_plane_url") if params else None) or settings.PUBLIC_URL
            config_content = config_content.replace(
                'url: "https://control.yourcdn.ru"', f'url: "{control_plane_url}"'
            )
            if node.api_key:
                config_content = config_content.replace(
                    'api_key: "your-api-key-here"', f'api_key: "{node.api_key}"'
                )
            else:
                logger.warning(f"Node {node.name} has no API key set!")

            with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp:
                tmp.write(config_content)
                tmp_config_path = tmp.name

            files_to_upload.append((tmp_config_path, "/opt/cdn_waf/config.yaml"))

        try:
            await EdgeNodeService.execute_command(
                node, "mkdir -p /opt/cdn_waf || sudo mkdir -p /opt/cdn_waf"
            )
            await EdgeNodeService.execute_command(
                node, "chown -R $USER:$USER /opt/cdn_waf || sudo chown -R $USER:$USER /opt/cdn_waf"
            )
            for local, remote in files_to_upload:
                if not await EdgeNodeService.upload_file(node, local, remote):
                    return EdgeNodeCommandResult(
                        success=False, stdout="",
                        stderr=f"Failed to upload {local}",
                        exit_code=1, execution_time=0,
                    )
        finally:
            if tmp_config_path:
                os.unlink(tmp_config_path)

        nginx_check = await EdgeNodeService.execute_command(node, "command -v nginx")
        if nginx_check.success:
            logger.info(f"Configuring nginx for CDN on node {node.name}")
            configure_result = await EdgeComponentService.run_setup_script(node, "configure_nginx")
            if not configure_result.success:
                logger.warning(f"Failed to configure nginx: {configure_result.stderr}")

        if settings.MAXMIND_ACCOUNT_ID and settings.MAXMIND_LICENSE_KEY:
            logger.info(f"Configuring GeoIP on node {node.name}")
            await EdgeComponentService.configure_geoip(node)

        return await EdgeComponentService.run_setup_script(node, "install_agent_service")

    @staticmethod
    async def configure_geoip(node: EdgeNode) -> bool:
        """Configure GeoIP on edge node with MaxMind credentials"""
        from app.services.edge_service import EdgeNodeService

        account_id = settings.MAXMIND_ACCOUNT_ID
        license_key = settings.MAXMIND_LICENSE_KEY

        if not account_id or not license_key:
            logger.warning(f"MaxMind credentials not configured, skipping GeoIP setup on {node.name}")
            return False

        geoip_conf = (
            f"# GeoIP.conf - Auto-configured by FlareCloud\n"
            f"AccountID {account_id}\n"
            f"LicenseKey {license_key}\n"
            f"EditionIDs GeoLite2-Country\n"
            f"DatabaseDirectory /usr/share/GeoIP\n"
        )

        try:
            escaped_conf = geoip_conf.replace("'", "'\\''")
            cmd = f"echo '{escaped_conf}' | sudo tee /etc/GeoIP.conf > /dev/null && sudo chmod 600 /etc/GeoIP.conf"
            result = await EdgeNodeService.execute_command(node, cmd)
            if not result.success:
                logger.error(f"Failed to write GeoIP.conf on {node.name}: {result.stderr}")
                return False

            logger.info(f"Downloading GeoIP database on {node.name}...")
            update_result = await EdgeNodeService.execute_command(
                node, "geoipupdate -v 2>&1 || echo 'geoipupdate not installed'", timeout=120
            )
            if "GeoLite2-Country" in update_result.stdout:
                logger.info(f"GeoIP database downloaded successfully on {node.name}")
            elif "not installed" in update_result.stdout:
                logger.warning(f"geoipupdate not installed on {node.name}")
            else:
                logger.warning(f"GeoIP update result on {node.name}: {update_result.stdout}")
            return True
        except Exception as e:
            logger.error(f"Failed to configure GeoIP on {node.name}: {e}")
            return False
