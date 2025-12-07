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
             
             # Also upload alembic.ini explicitly here
             if os.path.exists("alembic.ini"):
                 success, error = await DNSNodeService.upload_file(node, "alembic.ini", "/opt/cdn_waf/alembic.ini")
                 if not success:
                     logger.warning(f"Failed to upload alembic.ini to {node.name}: {error}")
             
             # Upload alembic directory if it exists locally
             if os.path.exists("alembic"):
                 with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_alembic_zip:
                     shutil.make_archive(tmp_alembic_zip.name.replace('.zip', ''), 'zip', root_dir='.', base_dir='alembic')
                     alembic_zip_path = tmp_alembic_zip.name
                 
                 try:
                     success, error = await DNSNodeService.upload_file(node, alembic_zip_path, "/opt/cdn_waf/alembic.zip")
                     if success:
                         await DNSNodeService.execute_command(node, "cd /opt/cdn_waf && (apt-get install -y unzip || true) && unzip -o alembic.zip && rm alembic.zip", timeout=60)
                 finally:
                     if os.path.exists(alembic_zip_path):
                         os.unlink(alembic_zip_path)

        finally:
             if os.path.exists(zip_path):
                 os.unlink(zip_path)
             
        # Unzip
        unzip_cmd = "cd /opt/cdn_waf && (apt-get install -y unzip || true) && unzip -o app.zip && rm app.zip"
        return await DNSNodeService.execute_command(node, unzip_cmd, timeout=60)

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
        """Run database migrations"""
        # Ensure alembic.ini exists (it should be there from deploy_code/install_python)
        # Try to upload it again just in case it's missing
        if os.path.exists("alembic.ini"):
             await DNSNodeService.upload_file(node, "alembic.ini", "/opt/cdn_waf/alembic.ini")
        
        # Also ensure alembic directory is present (might be missing if only app code updated)
        if os.path.exists("alembic"):
             import shutil
             import tempfile
             with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_alembic_zip:
                 shutil.make_archive(tmp_alembic_zip.name.replace('.zip', ''), 'zip', root_dir='.', base_dir='alembic')
                 alembic_zip_path = tmp_alembic_zip.name
             try:
                 success, _ = await DNSNodeService.upload_file(node, alembic_zip_path, "/opt/cdn_waf/alembic.zip")
                 if success:
                     await DNSNodeService.execute_command(node, "cd /opt/cdn_waf && (apt-get install -y unzip || true) && unzip -o alembic.zip && rm alembic.zip", timeout=60)
             finally:
                 if os.path.exists(alembic_zip_path):
                     os.unlink(alembic_zip_path)

        cmd = "cd /opt/cdn_waf && ./venv/bin/alembic upgrade head"
        return await DNSNodeService.execute_command(node, cmd, timeout=120)
    
    @staticmethod
    async def sync_database(node: DNSNode, db_session: AsyncSession) -> DNSNodeCommandResult:
        """Sync domains and records from central DB to node DB"""
        
        # 1. Fetch data from central DB
        # We need to sync users first because of foreign key constraints in organizations
        users = await db_session.execute(text("SELECT * FROM users"))
        users_data = users.all()

        organizations = await db_session.execute(text("SELECT * FROM organizations"))
        organizations_data = organizations.all()
        
        domains = await db_session.execute(text("SELECT * FROM domains"))
        domains_data = domains.all()
        
        dns_records = await db_session.execute(text("SELECT * FROM dns_records"))
        dns_records_data = dns_records.all()
        
        # 2. Generate SQL Dump
        # Using pg_dump would be cleaner but requires connection string matching. 
        # Generating INSERTs is safer for mismatched environments (e.g. if we want to overwrite everything)
        # But for sync, TRUNCATE + INSERT is easiest way to ensure consistency
        
        sql_lines = [
            "\\set ON_ERROR_STOP on",
            "BEGIN;",
            # Truncate in correct order (dependent tables first if we didn't use CASCADE, but CASCADE handles it)
            # However, to be safe and clear:
            # dns_records -> domains
            # domains -> organizations
            # organizations -> users
            # So truncating users CASCADE should clear everything if everything is linked.
            # But explicit list is better.
            "TRUNCATE TABLE dns_records, domains, organizations, users, domain_tls_settings, origins, cache_rules, waf_rules, rate_limits, ip_access_rules, certificates CASCADE;",
        ]
        
        # Users
        for user in users_data:
            # Handle booleans and NULLs
            is_active = 'TRUE' if user.is_active else 'FALSE'
            is_superuser = 'TRUE' if user.is_superuser else 'FALSE'
            last_login = f"'{user.last_login}'" if user.last_login else "NULL"
            
            sql_lines.append(
                f"INSERT INTO users (id, email, password_hash, full_name, is_active, is_superuser, last_login, created_at, updated_at) "
                f"VALUES ({user.id}, '{user.email}', '{user.password_hash}', '{user.full_name}', {is_active}, {is_superuser}, {last_login}, '{user.created_at}', '{user.updated_at}');"
            )

        # Organizations
        for org in organizations_data:
            # Manually map columns instead of using mapped metadata to avoid reflection issues
            sql_lines.append(
                f"INSERT INTO organizations (id, name, owner_id, created_at, updated_at) "
                f"VALUES ({org.id}, '{org.name}', {org.owner_id}, '{org.created_at}', '{org.updated_at}');"
            )

        # Domains
        for domain in domains_data:
            # Handle potentially null values safely
            ns_verified_at = f"'{domain.ns_verified_at}'" if domain.ns_verified_at else "NULL"
            verification_token = f"'{domain.verification_token}'" if domain.verification_token else "NULL"
            
            sql_lines.append(
                f"INSERT INTO domains (id, organization_id, name, status, verification_token, ns_verified, ns_verified_at, created_at, updated_at) "
                f"VALUES ({domain.id}, {domain.organization_id}, '{domain.name}', '{domain.status}', {verification_token}, {'TRUE' if domain.ns_verified else 'FALSE'}, {ns_verified_at}, '{domain.created_at}', '{domain.updated_at}');"
            )
            
        # DNS Records
        for record in dns_records_data:
            priority = str(record.priority) if record.priority is not None else "NULL"
            weight = str(record.weight) if record.weight is not None else "NULL"
            comment = f"'{record.comment.replace(chr(39), chr(39)+chr(39))}'" if record.comment else "NULL"
            
            # Escape content properly
            content = record.content.replace("'", "''")
            
            sql_lines.append(
                f"INSERT INTO dns_records (id, domain_id, type, name, content, ttl, priority, weight, proxied, comment, created_at, updated_at) "
                f"VALUES ({record.id}, {record.domain_id}, '{record.type}', '{record.name}', '{content}', {record.ttl}, {priority}, {weight}, {'TRUE' if record.proxied else 'FALSE'}, {comment}, '{record.created_at}', '{record.updated_at}');"
            )

        sql_lines.append("COMMIT;")
        
        sql_content = "\n".join(sql_lines)
        
        # 3. Upload and Execute
        with tempfile.NamedTemporaryFile(mode='w', suffix=".sql", delete=False, encoding='utf-8') as tmp_sql:
            tmp_sql.write(sql_content)
            tmp_sql_path = tmp_sql.name
            
        try:
            # Upload
            success, error = await DNSNodeService.upload_file(node, tmp_sql_path, "/tmp/sync_db.sql")
            if not success:
                return DNSNodeCommandResult(success=False, stdout="", stderr=f"Failed to upload SQL: {error}", exit_code=1, execution_time=0)
            
            # Fix permissions so postgres user can read it
            await DNSNodeService.execute_command(node, "chmod 644 /tmp/sync_db.sql")

            # Execute
            # Assume DB name is cdn_waf and user cdn_user (standard from setup)
            # OR we can parse .env on the node.
            # But simpler: use 'sudo -u postgres psql cdn_waf -f /tmp/sync_db.sql' 
            # as our setup script creates it this way.
            
            cmd = "sudo -u postgres psql cdn_waf -f /tmp/sync_db.sql"
            # Capture both stdout and stderr to debug sql errors
            res = await DNSNodeService.execute_command(node, cmd, timeout=60)
            
            if not res.success:
                 # If sync failed, log the output and return error
                 logger.error(f"DB Sync failed on {node.name}. Output: {res.stdout} Error: {res.stderr}")
                 return res
            
            return res
            
        finally:
            if os.path.exists(tmp_sql_path):
                os.unlink(tmp_sql_path)

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
            elif component == "migrations":
                return await DNSNodeService.run_migrations(node)
            elif component == "dns_server": # Alias for full install? Or just service?
                 # If user clicks "Install" on "DNS Server" component in old UI
                 return await DNSNodeService.install_node(node)
            elif component == "database" and db:
                 return await DNSNodeService.sync_database(node, db)
        
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
        
        if component == "database" and action == "sync" and db:
             return await DNSNodeService.sync_database(node, db)

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

        if component == "migrations":
             # Check if alembic exists
             res = await DNSNodeService.execute_command(node, "[ -x /opt/cdn_waf/venv/bin/alembic ]")
             # Maybe check current revision? Too complex for now.
             return DNSComponentStatus(
                 component=component, 
                 installed=res.success, 
                 running=True, 
                 status_text="Ready" if res.success else "Missing Alembic"
             )
        
        if component == "database":
             # Check if we can query the DB
             res = await DNSNodeService.execute_command(node, "sudo -u postgres psql cdn_waf -c 'SELECT count(*) FROM domains'")
             if res.success:
                 try:
                     count = res.stdout.split('\n')[2].strip()
                     return DNSComponentStatus(
                         component=component,
                         installed=True,
                         running=True,
                         status_text=f"OK ({count} domains)"
                     )
                 except:
                     pass
             
             return DNSComponentStatus(
                 component=component,
                 installed=False,
                 running=False,
                 status_text="Error"
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
