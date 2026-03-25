"""DNS node management service"""
import asyncio
import logging
import os
import tempfile
import shutil
import csv
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dns_node import DNSNode
from app.schemas.dns_node import (
    DNSNodeCreate,
    DNSNodeUpdate,
    DNSNodeStats,
    DNSNodeCommandResult,
    DNSComponentStatus
)
from app.services.ssh_utils import SSHCredentials, ssh_execute, ssh_upload

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
        creds = SSHCredentials.from_node(node)
        result = await ssh_execute(creds, command, timeout)
        return DNSNodeCommandResult(
            success=result.success,
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            execution_time=result.execution_time,
        )

    @staticmethod
    async def upload_file(node: DNSNode, local_path: str, remote_path: str) -> Tuple[bool, str]:
        """Upload file via SCP"""
        creds = SSHCredentials.from_node(node)
        return await ssh_upload(creds, local_path, remote_path)

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
        return await DNSNodeService.execute_command(node, "/tmp/setup_dns.sh install_deps", timeout=300)

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
        
        return await DNSNodeService.execute_command(node, "/tmp/setup_dns.sh install_python", timeout=300)

    @staticmethod
    async def update_app_code(node: DNSNode) -> DNSNodeCommandResult:
        import shutil
        import tempfile
        
        tmpdir = tempfile.mkdtemp()
        try:
            bundle_root = os.path.join(tmpdir, "bundle")
            os.makedirs(bundle_root, exist_ok=True)
            
            shutil.copytree("app", os.path.join(bundle_root, "app"))
            if os.path.exists("alembic"):
                shutil.copytree("alembic", os.path.join(bundle_root, "alembic"))
            if os.path.exists("alembic.ini"):
                shutil.copy("alembic.ini", os.path.join(bundle_root, "alembic.ini"))
            if os.path.exists("requirements.txt"):
                shutil.copy("requirements.txt", os.path.join(bundle_root, "requirements.txt"))
            
            zip_base = os.path.join(tmpdir, "bundle")
            zip_path = shutil.make_archive(zip_base, "zip", root_dir=bundle_root)
            
            await DNSNodeService.execute_command(node, "mkdir -p /opt/cdn_waf")
            success, error = await DNSNodeService.upload_file(node, zip_path, "/opt/cdn_waf/bundle.zip")
            if not success:
                return DNSNodeCommandResult(success=False, stdout="", stderr=f"Bundle upload failed: {error}", exit_code=1, execution_time=0)
            
            unzip_cmd = "cd /opt/cdn_waf && (apt-get install -y unzip || true) && unzip -o bundle.zip && rm bundle.zip"
            upload_res = await DNSNodeService.execute_command(node, unzip_cmd, timeout=120)
            if not upload_res.success:
                return upload_res

            restart_res = await DNSNodeService.execute_command(node, "systemctl restart cdn-waf-dns", timeout=30)
            stdout = upload_res.stdout + "\n[auto] Service restarted" if restart_res.success else upload_res.stdout + "\n[warn] Service restart failed"
            return DNSNodeCommandResult(
                success=upload_res.success,
                stdout=stdout,
                stderr=upload_res.stderr + (restart_res.stderr or ""),
                exit_code=upload_res.exit_code,
                execution_time=upload_res.execution_time,
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @staticmethod
    async def update_config(node: DNSNode) -> DNSNodeCommandResult:
        from app.core.config import settings
        # Create a full .env file with all required settings
        env_content = f"""
DATABASE_URL={settings.DATABASE_URL}
SECRET_KEY={settings.SECRET_KEY}
REDIS_URL={settings.REDIS_URL}
CELERY_BROKER_URL={settings.CELERY_BROKER_URL}
CELERY_RESULT_BACKEND={settings.CELERY_RESULT_BACKEND}
JWT_SECRET_KEY={settings.JWT_SECRET_KEY}
ACME_EMAIL={settings.ACME_EMAIL}
"""
        
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
        return await DNSNodeService.execute_command(node, "/tmp/setup_dns.sh install_dns_service", timeout=60)

    @staticmethod
    async def install_certbot(node: DNSNode) -> DNSNodeCommandResult:
        res = await DNSNodeService._ensure_setup_script(node)
        if not res.success: return res
        return await DNSNodeService.execute_command(node, "/tmp/setup_dns.sh install_certbot")

    @staticmethod
    async def run_migrations(node: DNSNode) -> DNSNodeCommandResult:
        """Run database migrations with auto-recovery for stale revision IDs."""
        base_dir = "cd /opt/cdn_waf"
        alembic = "./venv/bin/alembic"

        res = await DNSNodeService.execute_command(
            node, f"{base_dir} && {alembic} upgrade head", timeout=180
        )
        if res.success:
            return res

        if "Can't locate revision" in (res.stdout or "") + (res.stderr or ""):
            logger.warning(f"Alembic revision mismatch on {node.name}, stamping head and retrying")
            stamp = await DNSNodeService.execute_command(
                node, f"{base_dir} && {alembic} stamp head", timeout=30
            )
            if not stamp.success:
                return DNSNodeCommandResult(
                    success=False,
                    stdout=res.stdout + "\n" + stamp.stdout,
                    stderr=f"stamp head also failed: {stamp.stderr}",
                    exit_code=1, execution_time=0,
                )
            retry = await DNSNodeService.execute_command(
                node, f"{base_dir} && {alembic} upgrade head", timeout=180
            )
            retry_stdout = res.stdout + "\n[auto] stamped head, retrying...\n" + retry.stdout
            return DNSNodeCommandResult(
                success=retry.success, stdout=retry_stdout,
                stderr=retry.stderr, exit_code=retry.exit_code,
                execution_time=retry.execution_time,
            )

        return res
    
    @staticmethod
    async def sync_database(node: DNSNode, db_session: AsyncSession) -> DNSNodeCommandResult:
        """Sync domains and records from central DB to node DB via API"""
        import httpx
        from app.schemas.sync import (
            DNSSyncPayload, UserSync, OrganizationSync, DomainSync, 
            DNSRecordSync, EdgeNodeSync, DNSNodeSync
        )
        
        try:
            # 1. Fetch data from central DB
            users = (await db_session.execute(text("SELECT * FROM users"))).all()
            organizations = (await db_session.execute(text("SELECT * FROM organizations"))).all()
            domains = (await db_session.execute(text("SELECT * FROM domains"))).all()
            dns_records = (await db_session.execute(text("SELECT * FROM dns_records"))).all()
            edge_nodes = (await db_session.execute(text("SELECT * FROM edge_nodes"))).all()
            dns_nodes = (await db_session.execute(text("SELECT * FROM dns_nodes"))).all()
            
            # 2. Construct Payload
            def row_to_dict(row):
                return dict(row._mapping)

            payload = DNSSyncPayload(
                users=[UserSync(**row_to_dict(u)) for u in users],
                organizations=[OrganizationSync(**row_to_dict(o)) for o in organizations],
                domains=[DomainSync(**row_to_dict(d)) for d in domains],
                records=[DNSRecordSync(**row_to_dict(r)) for r in dns_records],
                edge_nodes=[EdgeNodeSync(**row_to_dict(n)) for n in edge_nodes],
                dns_nodes=[DNSNodeSync(**row_to_dict(n)) for n in dns_nodes],
            )
            
            # 3. Send to Node API
            # Need to determine port, assuming 8000 for now
            api_url = f"http://{node.ip_address}:8000/api/v1/sync"
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    api_url, 
                    json=payload.model_dump(mode='json'),
                    timeout=60.0
                )
                
                if response.status_code == 200:
                    return DNSNodeCommandResult(
                        success=True,
                        stdout=str(response.json()),
                        stderr="",
                        exit_code=0,
                        execution_time=response.elapsed.total_seconds()
                    )
                else:
                    return DNSNodeCommandResult(
                        success=False,
                        stdout=response.text,
                        stderr=f"API Error: {response.status_code}",
                        exit_code=1,
                        execution_time=response.elapsed.total_seconds()
                    )
                    
        except Exception as e:
            logger.error(f"Sync failed to {node.name}: {e}")
            return DNSNodeCommandResult(
                success=False,
                stdout="",
                stderr=str(e),
                exit_code=1,
                execution_time=0.0
            )

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
            ("Config", DNSNodeService.update_config),
            ("Dependencies", DNSNodeService.install_dependencies),
            ("Python Env", DNSNodeService.install_python_env),
            ("Certbot", DNSNodeService.install_certbot),
            ("App Code", DNSNodeService.update_app_code),
            ("Migrations", DNSNodeService.run_migrations),
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
    async def manage_component_action(node: DNSNode, component: str, action: str, db: AsyncSession = None) -> DNSNodeCommandResult:
        from app.services.dns_node_component_service import DNSNodeComponentService
        return await DNSNodeComponentService.manage_component_action(node, component, action, db)

    @staticmethod
    async def get_component_status(node: DNSNode, component: str) -> DNSComponentStatus:
        from app.services.dns_node_component_service import DNSNodeComponentService
        return await DNSNodeComponentService.get_component_status(node, component)

    @staticmethod
    async def check_health(node: DNSNode, db: AsyncSession = None) -> Dict[str, Any]:
        from app.services.dns_node_component_service import DNSNodeComponentService
        return await DNSNodeComponentService.check_health(node, db)
