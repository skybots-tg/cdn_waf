"""Edge node management service"""
import asyncio
import logging
import re
import os
import tempfile
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
import asyncssh

from app.models.edge_node import EdgeNode
from app.schemas.edge_node import (
    EdgeNodeCreate,
    EdgeNodeUpdate,
    EdgeNodeStats,
    EdgeNodeCommandResult,
    EdgeComponentStatus
)

from app.models.log import RequestLog

logger = logging.getLogger(__name__)


class EdgeNodeService:
    """Service for managing edge nodes"""
    
    @staticmethod
    async def get_nodes(
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        status: Optional[str] = None,
        location: Optional[str] = None
    ) -> List[EdgeNode]:
        """Get list of edge nodes with filters"""
        query = select(EdgeNode)
        
        if status:
            query = query.where(EdgeNode.status == status)
        if location:
            query = query.where(EdgeNode.location_code == location)
        
        query = query.offset(skip).limit(limit).order_by(EdgeNode.created_at.desc())
        result = await db.execute(query)
        return list(result.scalars().all())
    
    @staticmethod
    async def get_node(db: AsyncSession, node_id: int) -> Optional[EdgeNode]:
        """Get edge node by ID"""
        result = await db.execute(select(EdgeNode).where(EdgeNode.id == node_id))
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_node_by_name(db: AsyncSession, name: str) -> Optional[EdgeNode]:
        """Get edge node by name"""
        result = await db.execute(select(EdgeNode).where(EdgeNode.name == name))
        return result.scalar_one_or_none()
    
    @staticmethod
    async def create_node(db: AsyncSession, node_data: EdgeNodeCreate) -> EdgeNode:
        """Create new edge node"""
        node = EdgeNode(
            name=node_data.name,
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
        node_data: EdgeNodeUpdate
    ) -> Optional[EdgeNode]:
        """Update edge node"""
        node = await EdgeNodeService.get_node(db, node_id)
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
        """Delete edge node"""
        node = await EdgeNodeService.get_node(db, node_id)
        if not node:
            return False
        
        await db.delete(node)
        await db.commit()
        return True
    
    @staticmethod
    async def get_stats(db: AsyncSession) -> EdgeNodeStats:
        """Get edge nodes statistics"""
        # Total count
        total_result = await db.execute(select(func.count(EdgeNode.id)))
        total = total_result.scalar() or 0
        
        # Count by status
        online_result = await db.execute(
            select(func.count(EdgeNode.id)).where(EdgeNode.status == "online")
        )
        online = online_result.scalar() or 0
        
        offline_result = await db.execute(
            select(func.count(EdgeNode.id)).where(EdgeNode.status == "offline")
        )
        offline = offline_result.scalar() or 0
        
        maintenance_result = await db.execute(
            select(func.count(EdgeNode.id)).where(EdgeNode.status == "maintenance")
        )
        maintenance = maintenance_result.scalar() or 0
        
        # Calculate real bandwidth (sum bytes_sent)
        bandwidth_result = await db.execute(
            select(func.sum(RequestLog.bytes_sent))
        )
        total_bytes = bandwidth_result.scalar() or 0
        total_bandwidth_gb = round(total_bytes / (1024 * 1024 * 1024), 2)

        # Calculate real total requests
        requests_result = await db.execute(
            select(func.count(RequestLog.id))
        )
        total_requests = requests_result.scalar() or 0
        
        return EdgeNodeStats(
            total_nodes=total,
            online_nodes=online,
            offline_nodes=offline,
            maintenance_nodes=maintenance,
            total_bandwidth=total_bandwidth_gb,
            total_requests=total_requests
        )
    
    @staticmethod
    async def check_node_health(node: EdgeNode) -> Dict[str, Any]:
        """Check edge node health via SSH"""
        # Define commands to run
        commands = [
            # Check CPU: grep 'cpu ' /proc/stat | awk '{usage=($2+$4)*100/($2+$4+$5)} END {print usage}'
            "grep 'cpu ' /proc/stat | awk '{usage=($2+$4)*100/($2+$4+$5)} END {print usage}'",
            # Check Memory: free | grep Mem | awk '{print $3/$2 * 100.0}'
            "free | grep Mem | awk '{print $3/$2 * 100.0}'",
            # Check Disk: df -h / | tail -1 | awk '{print $5}' | sed 's/%//'
            "df -h / | tail -1 | awk '{print $5}' | sed 's/%//'"
        ]
        
        try:
            results = []
            for cmd in commands:
                result = await EdgeNodeService.execute_command(node, cmd)
                if result.success:
                    results.append(result.stdout.strip())
                else:
                    results.append(None)
            
            # Parse results
            cpu_usage = float(results[0]) if results[0] else None
            memory_usage = float(results[1]) if results[1] else None
            disk_usage = float(results[2]) if results[2] else None
            
            # Update status based on success
            status = "online" if all(x is not None for x in results) else "offline"
            
            return {
                "status": status,
                "cpu_usage": cpu_usage,
                "memory_usage": memory_usage,
                "disk_usage": disk_usage
            }
            
        except Exception as e:
            logger.error(f"Health check failed for {node.name}: {e}")
            return {
                "status": "offline",
                "error": str(e)
            }
    
    @staticmethod
    async def execute_command(
        node: EdgeNode,
        command: str,
        timeout: int = 30
    ) -> EdgeNodeCommandResult:
        """Execute command on edge node via SSH"""
        ssh_host = node.ssh_host or node.ip_address
        ssh_port = node.ssh_port or 22
        ssh_user = node.ssh_user or "root"
        ssh_key = node.ssh_key
        ssh_password = node.ssh_password
        
        if not ssh_key and not ssh_password:
             return EdgeNodeCommandResult(
                success=False,
                stdout="",
                stderr="SSH credentials (key or password) not configured for this node",
                exit_code=1,
                execution_time=0.0
            )

        try:
            start_time = datetime.utcnow()
            
            # Import asyncssh locally to ensure it is available
            import asyncssh

            # Create connection options
            connect_kwargs = {
                "host": ssh_host,
                "port": ssh_port,
                "username": ssh_user,
                "known_hosts": None  # Security: In production, manage known_hosts!
            }

            if ssh_key:
                client_keys = [asyncssh.import_private_key(ssh_key)]
                connect_kwargs["client_keys"] = client_keys
            elif ssh_password:
                connect_kwargs["password"] = ssh_password

            async with asyncssh.connect(**connect_kwargs) as conn:
                result = await conn.run(command, timeout=timeout)
                
                execution_time = (datetime.utcnow() - start_time).total_seconds()
                
                return EdgeNodeCommandResult(
                    success=result.exit_status == 0,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    exit_code=result.exit_status,
                    execution_time=execution_time
                )
            
        except Exception as e:
            logger.error(f"Failed to execute command on node {node.name}: {e}")
            return EdgeNodeCommandResult(
                success=False,
                stdout="",
                stderr=str(e),
                exit_code=1,
                execution_time=0.0
            )
    
    @staticmethod
    async def get_component_status(
        node: EdgeNode,
        component: str
    ) -> EdgeComponentStatus:
        """Get status of component on edge node"""
        
        # Virtual components handling
        if component == "system":
             # Check if basic tools are installed
             cmd = "which curl && which git"
             result = await EdgeNodeService.execute_command(node, cmd)
             return EdgeComponentStatus(
                component=component,
                installed=result.success,
                running=True, # System is always running
                version=None,
                status_text="Installed" if result.success else "Not installed"
            )
        
        if component == "python":
             # Check venv
             cmd = "[ -f /opt/cdn_waf/venv/bin/python ] && echo 'exists'"
             result = await EdgeNodeService.execute_command(node, cmd)
             return EdgeComponentStatus(
                component=component,
                installed=result.success,
                running=True,
                version=None,
                status_text="Active" if result.success else "Missing venv"
            )
            
        if component == "certbot":
             # Check certbot version
             cmd = "certbot --version"
             result = await EdgeNodeService.execute_command(node, cmd)
             
             installed = result.success
             version = None
             if installed and result.stdout:
                 # Output format: certbot 1.21.0
                 parts = result.stdout.strip().split()
                 if len(parts) >= 2:
                     version = parts[1]
             
             # Certbot isn't a running service, it's a tool. 
             # So we consider it 'running' (available) if installed.
             # Or better: running=False but installed=True is normal state.
             
             return EdgeComponentStatus(
                component=component,
                installed=installed,
                running=installed, # For CLI tools, installed means ready/running
                version=version,
                status_text="Ready" if installed else "Not installed"
            )
            
        service_name = component
        if component == "agent":
             service_name = "cdn-waf-agent"

        # Command to check if service is running
        cmd = f"systemctl is-active {service_name}"
        result = await EdgeNodeService.execute_command(node, cmd)
        
        status_output = result.stdout.strip()
        running = status_output == "active"
        
        if not result.success:
             # Command failed or service inactive
             if "SSH" in result.stderr:
                 status_text = "Connection Error"
             elif status_output:
                 status_text = status_output # e.g. inactive, failed
             else:
                 status_text = "Stopped" # Default for exit code non-zero without output
        elif status_output:
            status_text = status_output
        else:
            status_text = "unknown"
        
        # Check version if running
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
        
        # Check if installed
        installed = running
        if not installed:
            # Try to check via which/command -v
            check_cmd = f"command -v {component}"
            if component == "redis":
                check_cmd = "command -v redis-server"
            elif component == "agent":
                check_cmd = "systemctl list-unit-files | grep cdn-waf-agent"
                
            c_res = await EdgeNodeService.execute_command(node, check_cmd)
            installed = c_res.success
        
        return EdgeComponentStatus(
            component=component,
            installed=installed,
            running=running,
            version=version,
            status_text=status_text
        )
    
    @staticmethod
    async def upload_file(
        node: EdgeNode,
        local_path: str,
        remote_path: str
    ) -> bool:
        """Upload file to edge node via SCP"""
        ssh_host = node.ssh_host or node.ip_address
        ssh_port = node.ssh_port or 22
        ssh_user = node.ssh_user or "root"
        ssh_key = node.ssh_key
        ssh_password = node.ssh_password
        
        try:
            import asyncssh
            
            connect_kwargs = {
                "host": ssh_host,
                "port": ssh_port,
                "username": ssh_user,
                "known_hosts": None
            }
            if ssh_key:
                client_keys = [asyncssh.import_private_key(ssh_key)]
                connect_kwargs["client_keys"] = client_keys
            elif ssh_password:
                connect_kwargs["password"] = ssh_password

            async with asyncssh.connect(**connect_kwargs) as conn:
                await asyncssh.scp(local_path, (conn, remote_path))
                return True
                
        except Exception as e:
            logger.error(f"Failed to upload file to {node.name}: {e}")
            return False

    @staticmethod
    async def run_setup_script(
        node: EdgeNode,
        action_name: str
    ) -> EdgeNodeCommandResult:
        """Run setup script action on node"""
        
        # Local paths
        setup_script = "edge_node/setup.sh"
        if not os.path.exists(setup_script):
            return EdgeNodeCommandResult(
                success=False, stdout="", stderr=f"Setup script not found: {setup_script}", 
                exit_code=1, execution_time=0
            )

        # Upload setup script
        if not await EdgeNodeService.upload_file(node, setup_script, "/tmp/setup.sh"):
             return EdgeNodeCommandResult(
                success=False, stdout="", stderr="Failed to upload setup script", 
                exit_code=1, execution_time=0
            )
            
        # Make executable
        await EdgeNodeService.execute_command(node, "chmod +x /tmp/setup.sh")
        
        # Run action
        cmd = f"/tmp/setup.sh {action_name}"
        return await EdgeNodeService.execute_command(node, cmd, timeout=300) # Increased timeout for install

    @staticmethod
    async def manage_component(
        node: EdgeNode,
        component: str,
        action: str
    ) -> EdgeNodeCommandResult:
        """Manage component on edge node (start, stop, restart, etc.)"""
        
        # Handle installations and updates
        if action == "install" or (component == "agent" and action == "update"):
            if component == "system":
                return await EdgeNodeService.run_setup_script(node, "install_deps")
            elif component == "nginx":
                return await EdgeNodeService.run_setup_script(node, "install_nginx")
            elif component == "certbot":
                return await EdgeNodeService.run_setup_script(node, "install_certbot")
            elif component == "python":
                return await EdgeNodeService.run_setup_script(node, "install_python")
            elif component == "agent":
                # Logic for agent install/update (upload files)
                
                # Prepare config
                config_content = ""
                with open("edge_node/config.example.yaml", "r") as f:
                    config_content = f.read()
                
                # Replace values
                config_content = config_content.replace("id: 1", f"id: {node.id}")
                config_content = config_content.replace('name: "ru-msk-01"', f'name: "{node.name}"')
                config_content = config_content.replace('location: "RU-MSK"', f'location: "{node.location_code}"')
                
                # Write to temp file
                with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
                    tmp.write(config_content)
                    tmp_config_path = tmp.name

                try:
                    files_to_upload = [
                        ("edge_node/edge_config_updater.py", "/opt/cdn_waf/edge_config_updater.py"),
                        ("edge_node/requirements.txt", "/opt/cdn_waf/requirements.txt"),
                        (tmp_config_path, "/opt/cdn_waf/config.yaml") 
                    ]
                    
                    # Ensure directory exists
                    await EdgeNodeService.execute_command(node, "mkdir -p /opt/cdn_waf")
                    
                    for local, remote in files_to_upload:
                        if not await EdgeNodeService.upload_file(node, local, remote):
                             return EdgeNodeCommandResult(
                                success=False, stdout="", stderr=f"Failed to upload {local}", 
                                exit_code=1, execution_time=0
                            )
                finally:
                    os.unlink(tmp_config_path)
                
                return await EdgeNodeService.run_setup_script(node, "install_agent_service")

        command_map = {
            "nginx": {
                "start": "systemctl start nginx || systemctl start openresty",
                "stop": "systemctl stop nginx || systemctl stop openresty",
                "restart": "systemctl restart nginx || systemctl restart openresty",
                "reload": "nginx -s reload || openresty -s reload",
                "status": "systemctl status nginx || systemctl status openresty",
                "update": "apt-get update && apt-get upgrade -y nginx openresty"
            },
            "redis": {
                "start": "systemctl start redis-server",  # Usually redis-server
                "stop": "systemctl stop redis-server",
                "restart": "systemctl restart redis-server",
                "status": "systemctl status redis-server",
                "install": "apt-get update && apt-get install -y redis-server"
            },
            "certbot": {
                "install": "apt-get update && apt-get install -y certbot python3-certbot-nginx",
                "status": "certbot --version"
            },
            "system": {
                "install": "apt-get update && apt-get install -y curl git build-essential python3-dev python3-venv"
            },
            "python": {
                "update": "cd /opt/cdn_waf && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt"
            },
            "agent": {
                "start": "systemctl start cdn-waf-agent",
                "stop": "systemctl stop cdn-waf-agent",
                "restart": "systemctl restart cdn-waf-agent",
                "status": "systemctl status cdn-waf-agent",
                # update is now handled above manually via file upload
            }
        }
        
        if component not in command_map or action not in command_map[component]:
            return EdgeNodeCommandResult(
                success=False,
                stdout="",
                stderr=f"Unknown component '{component}' or action '{action}'",
                exit_code=1,
                execution_time=0.0
            )
        
        command = command_map[component][action]
        return await EdgeNodeService.execute_command(node, command)
    
    @staticmethod
    async def update_heartbeat(db: AsyncSession, node_id: int) -> bool:
        """Update node heartbeat timestamp"""
        node = await EdgeNodeService.get_node(db, node_id)
        if not node:
            return False
        
        node.last_heartbeat = datetime.utcnow()
        node.status = "online"
        await db.commit()
        return True
    
    @staticmethod
    async def update_metrics(
        db: AsyncSession,
        node_id: int,
        cpu_usage: Optional[float] = None,
        memory_usage: Optional[float] = None,
        disk_usage: Optional[float] = None,
        status: str = "online"
    ) -> bool:
        """Update node metrics"""
        node = await EdgeNodeService.get_node(db, node_id)
        if not node:
            return False
        
        if cpu_usage is not None:
            node.cpu_usage = cpu_usage
        if memory_usage is not None:
            node.memory_usage = memory_usage
        if disk_usage is not None:
            node.disk_usage = disk_usage
        
        node.last_heartbeat = datetime.utcnow()
        node.status = status
        await db.commit()
        return True
