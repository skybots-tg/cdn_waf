"""Edge node management service"""
import asyncio
import logging
import re
import os
import tempfile
import secrets
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy import select, func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.edge_node import EdgeNode
from app.schemas.edge_node import (
    EdgeNodeCreate,
    EdgeNodeUpdate,
    EdgeNodeStats,
    EdgeNodeCommandResult,
    EdgeComponentStatus
)

from app.models.log import RequestLog
from app.core.config import settings
from app.services.ssh_utils import SSHCredentials, ssh_execute, ssh_upload

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
            ssh_password=node_data.ssh_password,
            api_key=secrets.token_urlsafe(32)
        )
        
        db.add(node)
        await db.commit()
        await db.refresh(node)
        return node
    
    @staticmethod
    async def regenerate_api_key(db: AsyncSession, node_id: int) -> Optional[str]:
        """Regenerate API key for edge node"""
        node = await EdgeNodeService.get_node(db, node_id)
        if not node:
            return None
            
        new_key = secrets.token_urlsafe(32)
        node.api_key = new_key
        await db.commit()
        return new_key
    
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
        from app.models.log import RequestLog
        
        node = await EdgeNodeService.get_node(db, node_id)
        if not node:
            return False
        
        # First, clear the edge_node_id from related logs to avoid FK constraint issues
        # This handles databases where the ondelete="SET NULL" constraint wasn't applied
        await db.execute(
            update(RequestLog)
            .where(RequestLog.edge_node_id == node_id)
            .values(edge_node_id=None)
        )
        
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
        creds = SSHCredentials.from_node(node)
        result = await ssh_execute(creds, command, timeout)
        return EdgeNodeCommandResult(
            success=result.success,
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            execution_time=result.execution_time,
        )
    
    # Component management delegated to EdgeComponentService
    @staticmethod
    async def get_component_status(node: EdgeNode, component: str) -> EdgeComponentStatus:
        from app.services.edge_component_service import EdgeComponentService
        return await EdgeComponentService.get_component_status(node, component)

    @staticmethod
    async def upload_file(node: EdgeNode, local_path: str, remote_path: str) -> bool:
        """Upload file to edge node via SCP"""
        creds = SSHCredentials.from_node(node)
        success, _error = await ssh_upload(creds, local_path, remote_path)
        return success

    @staticmethod
    async def run_setup_script(node: EdgeNode, action_name: str) -> EdgeNodeCommandResult:
        from app.services.edge_component_service import EdgeComponentService
        return await EdgeComponentService.run_setup_script(node, action_name)

    @staticmethod
    async def manage_component(node: EdgeNode, component: str, action: str, params: Optional[Dict[str, Any]] = None) -> EdgeNodeCommandResult:
        from app.services.edge_component_service import EdgeComponentService
        return await EdgeComponentService.manage_component(node, component, action, params)

    @staticmethod
    async def configure_geoip(node: EdgeNode) -> bool:
        from app.services.edge_component_service import EdgeComponentService
        return await EdgeComponentService.configure_geoip(node)
    
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
