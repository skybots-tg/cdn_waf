"""DNS node management service"""
import asyncio
import logging
import os
import tempfile
import shutil
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dns_node import DNSNode
from app.schemas.dns_node import (
    DNSNodeCreate,
    DNSNodeUpdate,
    DNSNodeStats,
    DNSNodeCommandResult,
    DNSComponentStatus
)

logger = logging.getLogger(__name__)

class DNSNodeService:
    """Service for managing DNS nodes"""
    
    @staticmethod
    async def get_nodes(
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        status: Optional[str] = None,
        location: Optional[str] = None
    ) -> List[DNSNode]:
        """Get list of DNS nodes"""
        query = select(DNSNode)
        if status:
            query = query.where(DNSNode.status == status)
        if location:
            query = query.where(DNSNode.location_code == location)
        
        query = query.offset(skip).limit(limit).order_by(DNSNode.created_at.desc())
        result = await db.execute(query)
        return list(result.scalars().all())
    
    @staticmethod
    async def get_node(db: AsyncSession, node_id: int) -> Optional[DNSNode]:
        """Get DNS node by ID"""
        result = await db.execute(select(DNSNode).where(DNSNode.id == node_id))
        return result.scalar_one_or_none()
    
    @staticmethod
    async def create_node(db: AsyncSession, node_data: DNSNodeCreate) -> DNSNode:
        """Create new DNS node"""
        node = DNSNode(
            name=node_data.name,
            hostname=node_data.hostname,
            ip_address=node_data.ip_address,
            ipv6_address=node_data.ipv6_address,
            location_code=node_data.location_code,
            country_code=node_data.country_code,
            city=node_data.city,
            datacenter=node_data.datacenter,
            enabled=node_data.enabled,
            status="unknown",
            ssh_host=node_data.ssh_host or node_data.ip_address,
            ssh_port=node_data.ssh_port,
            ssh_user=node_data.ssh_user,
            ssh_key=node_data.ssh_key,
            ssh_password=node_data.ssh_password
        )
        
        db.add(node)
        await db.commit()
        await db.refresh(node)
        return node
    
    @staticmethod
    async def update_node(
        db: AsyncSession,
        node_id: int,
        node_data: DNSNodeUpdate
    ) -> Optional[DNSNode]:
        """Update DNS node"""
        node = await DNSNodeService.get_node(db, node_id)
        if not node:
            return None
        
        update_data = node_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(node, field):
                setattr(node, field, value)
        
        await db.commit()
        await db.refresh(node)
        return node
    
    @staticmethod
    async def delete_node(db: AsyncSession, node_id: int) -> bool:
        """Delete DNS node"""
        node = await DNSNodeService.get_node(db, node_id)
        if not node:
            return False
        
        await db.delete(node)
        await db.commit()
        return True

    @staticmethod
    async def get_stats(db: AsyncSession) -> DNSNodeStats:
        """Get DNS nodes statistics"""
        total_result = await db.execute(select(func.count(DNSNode.id)))
        total = total_result.scalar() or 0
        
        online_result = await db.execute(
            select(func.count(DNSNode.id)).where(DNSNode.status == "online")
        )
        online = online_result.scalar() or 0
        
        offline_result = await db.execute(
            select(func.count(DNSNode.id)).where(DNSNode.status == "offline")
        )
        offline = offline_result.scalar() or 0
        
        return DNSNodeStats(
            total_nodes=total,
            online_nodes=online,
            offline_nodes=offline
        )

    @staticmethod
    async def execute_command(
        node: DNSNode,
        command: str,
        timeout: int = 30
    ) -> DNSNodeCommandResult:
        """Execute command via SSH"""
        ssh_host = node.ssh_host or node.ip_address
        ssh_port = node.ssh_port or 22
        ssh_user = node.ssh_user or "root"
        ssh_key = node.ssh_key
        ssh_password = node.ssh_password
        
        if not ssh_key and not ssh_password:
             return DNSNodeCommandResult(
                success=False, stdout="", stderr="SSH credentials not configured",
                exit_code=1, execution_time=0.0
            )

        try:
            start_time = datetime.utcnow()
            import asyncssh
            connect_kwargs = {
                "host": ssh_host, "port": ssh_port, "username": ssh_user,
                "known_hosts": None
            }

            if ssh_key:
                client_keys = [asyncssh.import_private_key(ssh_key)]
                connect_kwargs["client_keys"] = client_keys
            elif ssh_password:
                connect_kwargs["password"] = ssh_password

            async with asyncssh.connect(**connect_kwargs) as conn:
                result = await conn.run(command, timeout=timeout)
                execution_time = (datetime.utcnow() - start_time).total_seconds()
                
                return DNSNodeCommandResult(
                    success=result.exit_status == 0,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    exit_code=result.exit_status,
                    execution_time=execution_time
                )
        except Exception as e:
            logger.error(f"SSH Error on {node.name}: {e}")
            return DNSNodeCommandResult(
                success=False, stdout="", stderr=str(e), exit_code=1, execution_time=0.0
            )

    @staticmethod
    async def upload_file(node: DNSNode, local_path: str, remote_path: str) -> Tuple[bool, str]:
        """Upload file via SCP"""
        ssh_host = node.ssh_host or node.ip_address
        ssh_port = node.ssh_port or 22
        ssh_user = node.ssh_user or "root"
        ssh_key = node.ssh_key
        ssh_password = node.ssh_password
        
        try:
            import asyncssh
            connect_kwargs = {
                "host": ssh_host, "port": ssh_port, "username": ssh_user,
                "known_hosts": None
            }
            if ssh_key:
                connect_kwargs["client_keys"] = [asyncssh.import_private_key(ssh_key)]
            elif ssh_password:
                connect_kwargs["password"] = ssh_password

            async with asyncssh.connect(**connect_kwargs) as conn:
                await asyncssh.scp(local_path, (conn, remote_path))
                return True, ""
        except Exception as e:
            logger.error(f"Upload failed to {node.name}: {e}")
            return False, str(e)

    @staticmethod
    async def get_logs(node: DNSNode, lines: int = 100) -> str:
        """Get service logs"""
        cmd = f"journalctl -u cdn-waf-dns -n {lines} --no-pager"
        res = await DNSNodeService.execute_command(node, cmd)
        return res.stdout if res.success else f"Error reading logs: {res.stderr}"

    # Granular Installation Methods
    
    @staticmethod
    async def _ensure_setup_script(node: DNSNode) -> DNSNodeCommandResult:
        setup_script = "dns_node/setup.sh"
        if not os.path.exists(setup_script):
             return DNSNodeCommandResult(success=False, stdout="", stderr="Setup script missing", exit_code=1, execution_time=0)
        
        # Check if remote exists? Just upload.
        success, error = await DNSNodeService.upload_file(node, setup_script, "/tmp/setup_dns.sh")
        if not success:
             return DNSNodeCommandResult(success=False, stdout="", stderr=f"Upload setup script failed: {error}", exit_code=1, execution_time=0)
        
        return await DNSNodeService.execute_command(node, "chmod +x /tmp/setup_dns.sh")

    @staticmethod
    async def install_dependencies(node: DNSNode) -> DNSNodeCommandResult:
        res = await DNSNodeService._ensure_setup_script(node)
        if not res.success: return res
        return await DNSNodeService.execute_command(node, "/tmp/setup_dns.sh install_deps")

    @staticmethod
    async def install_python_env(node: DNSNode) -> DNSNodeCommandResult:
        res = await DNSNodeService._ensure_setup_script(node)
        if not res.success: return res
        
        # Upload requirements
        success, error = await DNSNodeService.upload_file(node, "requirements.txt", "/opt/cdn_waf/requirements.txt")
        if not success:
             # Try creating dir first
             await DNSNodeService.execute_command(node, "mkdir -p /opt/cdn_waf")
             success, error = await DNSNodeService.upload_file(node, "requirements.txt", "/opt/cdn_waf/requirements.txt")
             if not success:
                 return DNSNodeCommandResult(success=False, stdout="", stderr=f"Requirements upload failed: {error}", exit_code=1, execution_time=0)
        
        return await DNSNodeService.execute_command(node, "/tmp/setup_dns.sh install_python")

    @staticmethod
    async def update_app_code(node: DNSNode) -> DNSNodeCommandResult:
        import shutil
        import tempfile
        
        # Zip the app
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_zip:
             shutil.make_archive(tmp_zip.name.replace('.zip', ''), 'zip', root_dir='.', base_dir='app')
             zip_path = tmp_zip.name
        
        try:
             # Ensure dir exists
             await DNSNodeService.execute_command(node, "mkdir -p /opt/cdn_waf")
             
             success, error = await DNSNodeService.upload_file(node, zip_path, "/opt/cdn_waf/app.zip")
             if not success:
                 return DNSNodeCommandResult(success=False, stdout="", stderr=f"App upload failed: {error}", exit_code=1, execution_time=0)
        finally:
             if os.path.exists(zip_path):
                 os.unlink(zip_path)
             
        # Unzip
        unzip_cmd = "cd /opt/cdn_waf && (apt-get install -y unzip || true) && unzip -o app.zip && rm app.zip"
        return await DNSNodeService.execute_command(node, unzip_cmd)

    @staticmethod
    async def update_config(node: DNSNode) -> DNSNodeCommandResult:
        from app.core.config import settings
        # We need to replace asyncpg with psycopg for sync driver in the remote node if needed
        # But for now passing the URL is enough.
        env_content = f"DATABASE_URL={settings.DATABASE_URL}\n"
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp_env:
             tmp_env.write(env_content)
             env_path = tmp_env.name
        
        try:
             await DNSNodeService.execute_command(node, "mkdir -p /opt/cdn_waf")
             success, error = await DNSNodeService.upload_file(node, env_path, "/opt/cdn_waf/.env")
             if not success:
                  return DNSNodeCommandResult(success=False, stdout="", stderr=f"Config upload failed: {error}", exit_code=1, execution_time=0)
        finally:
             if os.path.exists(env_path):
                 os.unlink(env_path)
        
        return DNSNodeCommandResult(success=True, stdout="Config updated", stderr="", exit_code=0, execution_time=0)

    @staticmethod
    async def install_service(node: DNSNode) -> DNSNodeCommandResult:
        res = await DNSNodeService._ensure_setup_script(node)
        if not res.success: return res
        return await DNSNodeService.execute_command(node, "/tmp/setup_dns.sh install_dns_service")

    @staticmethod
    async def install_certbot(node: DNSNode) -> DNSNodeCommandResult:
        res = await DNSNodeService._ensure_setup_script(node)
        if not res.success: return res
        return await DNSNodeService.execute_command(node, "/tmp/setup_dns.sh install_certbot")

    @staticmethod
    async def issue_certificate(node: DNSNode) -> DNSNodeCommandResult:
        """Issue SSL certificate for the node hostname"""
        cmd = f"certbot certonly --standalone -d {node.hostname} --non-interactive --agree-tos --email admin@yourcdn.ru" # TODO: use config email
        # Check if port 80 is free first?
        return await DNSNodeService.execute_command(node, cmd)

    @staticmethod
    async def install_node(node: DNSNode) -> DNSNodeCommandResult:
        """Full installation flow"""
        steps = [
            ("Dependencies", DNSNodeService.install_dependencies),
            ("Python Env", DNSNodeService.install_python_env),
            ("Certbot", DNSNodeService.install_certbot),
            ("App Code", DNSNodeService.update_app_code),
            ("Config", DNSNodeService.update_config),
            ("Service", DNSNodeService.install_service)
        ]
        
        stdout = []
        for name, func in steps:
            res = await func(node)
            stdout.append(f"[{name}] {res.stdout}")
            if not res.success:
                return DNSNodeCommandResult(
                    success=False, 
                    stdout="\n".join(stdout), 
                    stderr=f"[{name}] Failed: {res.stderr}", 
                    exit_code=res.exit_code, 
                    execution_time=0
                )
        
        return DNSNodeCommandResult(success=True, stdout="\n".join(stdout), stderr="", exit_code=0, execution_time=0)

    @staticmethod
    async def manage_component_action(node: DNSNode, component: str, action: str) -> DNSNodeCommandResult:
        if action == "install":
            if component == "dependencies":
                return await DNSNodeService.install_dependencies(node)
            elif component == "python_env":
                return await DNSNodeService.install_python_env(node)
            elif component == "app_code":
                return await DNSNodeService.update_app_code(node)
            elif component == "config":
                return await DNSNodeService.update_config(node)
            elif component == "dns_service":
                return await DNSNodeService.install_service(node)
            elif component == "certbot":
                return await DNSNodeService.install_certbot(node)
            elif component == "dns_server": # Alias for full install? Or just service?
                 # If user clicks "Install" on "DNS Server" component in old UI
                 return await DNSNodeService.install_node(node)
        
        if component == "certbot" and action == "issue":
             return await DNSNodeService.issue_certificate(node)

        # Service management
        if component in ["dns_service", "dns_server"]:
             cmd_map = {
                "start": "systemctl start cdn-waf-dns",
                "stop": "systemctl stop cdn-waf-dns",
                "restart": "systemctl restart cdn-waf-dns",
                "status": "systemctl status cdn-waf-dns"
            }
             if action in cmd_map:
                 return await DNSNodeService.execute_command(node, cmd_map[action])

        return DNSNodeCommandResult(
            success=False,
            stdout="",
            stderr=f"Unknown component or action: {component} {action}",
            exit_code=1,
            execution_time=0
        )

    @staticmethod
    async def get_component_status(node: DNSNode, component: str) -> DNSComponentStatus:
        """Get component status"""
        if component in ["dns_server", "dns_service"]:
             # Check if service file exists to determine "installed"
             check_installed = "systemctl list-unit-files cdn-waf-dns.service"
             res_installed = await DNSNodeService.execute_command(node, check_installed)
             is_installed = res_installed.success and "cdn-waf-dns.service" in res_installed.stdout
             
             cmd = "systemctl is-active cdn-waf-dns"
             res = await DNSNodeService.execute_command(node, cmd)
             running = res.stdout.strip() == "active"
             
             return DNSComponentStatus(
                 component=component,
                 installed=is_installed,
                 running=running,
                 status_text="Active" if running else ("Inactive" if is_installed else "Not Installed")
             )
        
        if component == "certbot":
             res = await DNSNodeService.execute_command(node, "certbot --version")
             installed = res.success
             version = res.stdout.strip().split()[-1] if installed and res.stdout else None
             return DNSComponentStatus(
                 component=component, 
                 installed=installed, 
                 running=True, # Always "running" as CLI tool
                 version=version,
                 status_text="Installed" if installed else "Missing"
             )

        # For other components, we can check existence of files
        if component == "dependencies":
             # Check for python3
             res = await DNSNodeService.execute_command(node, "which python3")
             return DNSComponentStatus(component=component, installed=res.success, running=True, status_text="Installed" if res.success else "Missing")
        
        if component == "python_env":
             res = await DNSNodeService.execute_command(node, "[ -d /opt/cdn_waf/venv ]")
             return DNSComponentStatus(component=component, installed=res.success, running=True, status_text="Installed" if res.success else "Missing")

        if component == "app_code":
             res = await DNSNodeService.execute_command(node, "[ -d /opt/cdn_waf/app ]")
             return DNSComponentStatus(component=component, installed=res.success, running=True, status_text="Installed" if res.success else "Missing")
        
        if component == "config":
             res = await DNSNodeService.execute_command(node, "[ -f /opt/cdn_waf/.env ]")
             return DNSComponentStatus(component=component, installed=res.success, running=True, status_text="Configured" if res.success else "Missing")

        return DNSComponentStatus(component=component, installed=False, running=False, status_text="Unknown")

    @staticmethod
    async def check_health(node: DNSNode, db: AsyncSession = None) -> Dict[str, Any]:
        """Check node health and update status"""
        
        # Check service status
        res = await DNSNodeService.get_component_status(node, "dns_service")
        
        status = "online" if res.running else ("offline" if res.installed else "unknown")
        
        # If we have DB session, update status
        if db:
            node.status = status
            node.last_heartbeat = datetime.utcnow()
            await db.commit()
            await db.refresh(node)
            
        return {
            "status": status,
            "service_active": res.running,
            "installed": res.installed
        }
