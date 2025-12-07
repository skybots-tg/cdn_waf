"""DNS node management service"""
import asyncio
import logging
import os
import tempfile
from typing import List, Optional, Dict, Any
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
    async def upload_file(node: DNSNode, local_path: str, remote_path: str) -> bool:
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
                return True
        except Exception as e:
            logger.error(f"Upload failed to {node.name}: {e}")
            return False

    @staticmethod
    async def install_node(node: DNSNode) -> DNSNodeCommandResult:
        """Install DNS node software"""
        # 1. Upload setup script
        setup_script = "dns_node/setup.sh"
        if not os.path.exists(setup_script):
             return DNSNodeCommandResult(success=False, stdout="", stderr="Setup script missing", exit_code=1, execution_time=0)
        
        if not await DNSNodeService.upload_file(node, setup_script, "/tmp/setup_dns.sh"):
             return DNSNodeCommandResult(success=False, stdout="", stderr="Upload failed", exit_code=1, execution_time=0)
        
        await DNSNodeService.execute_command(node, "chmod +x /tmp/setup_dns.sh")
        
        # 2. Upload requirements
        if not await DNSNodeService.upload_file(node, "requirements.txt", "/opt/cdn_waf/requirements.txt"):
             # Try creating dir first
             await DNSNodeService.execute_command(node, "mkdir -p /opt/cdn_waf")
             if not await DNSNodeService.upload_file(node, "requirements.txt", "/opt/cdn_waf/requirements.txt"):
                 return DNSNodeCommandResult(success=False, stdout="", stderr="Requirements upload failed", exit_code=1, execution_time=0)
        
        # 3. Upload App Code (simplified: just copying necessary files? No, we need the whole structure)
        # This is complex via SCP one-by-one. 
        # Better strategy: Zip the app and upload.
        import shutil
        
        # Create a temporary zip of 'app' folder
        # We need to include 'app' folder itself
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_zip:
             shutil.make_archive(tmp_zip.name.replace('.zip', ''), 'zip', root_dir='.', base_dir='app')
             zip_path = tmp_zip.name
        
        try:
             if not await DNSNodeService.upload_file(node, zip_path, "/opt/cdn_waf/app.zip"):
                 return DNSNodeCommandResult(success=False, stdout="", stderr="App upload failed", exit_code=1, execution_time=0)
        finally:
             os.unlink(zip_path)
             
        # 4. Unzip on remote
        unzip_cmd = "cd /opt/cdn_waf && apt-get update && apt-get install -y unzip && unzip -o app.zip && rm app.zip"
        await DNSNodeService.execute_command(node, unzip_cmd)

        # 5. Create .env file with DATABASE_URL
        # In production, we should handle this securely. 
        # Here we just assume we want to point to the central DB.
        from app.core.config import settings
        env_content = f"DATABASE_URL={settings.DATABASE_URL}\n"
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp_env:
             tmp_env.write(env_content)
             env_path = tmp_env.name
        
        try:
             await DNSNodeService.upload_file(node, env_path, "/opt/cdn_waf/.env")
        finally:
             os.unlink(env_path)

        # 6. Run setup script steps
        # Install deps
        await DNSNodeService.execute_command(node, "/tmp/setup_dns.sh install_deps")
        # Install python
        await DNSNodeService.execute_command(node, "/tmp/setup_dns.sh install_python")
        # Install service
        return await DNSNodeService.execute_command(node, "/tmp/setup_dns.sh install_dns_service")

    @staticmethod
    async def get_component_status(node: DNSNode, component: str) -> DNSComponentStatus:
        """Get component status"""
        if component == "dns_server":
             cmd = "systemctl is-active cdn-waf-dns"
             res = await DNSNodeService.execute_command(node, cmd)
             running = res.stdout.strip() == "active"
             return DNSComponentStatus(
                 component="dns_server",
                 installed=res.success or running, # if active, it is installed
                 running=running,
                 status_text="Active" if running else "Inactive"
             )
        
        # ... other components ...
        return DNSComponentStatus(component=component, installed=False, running=False, status_text="Unknown")

