"""Edge node management service"""
import asyncio
import logging
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
            status="unknown"
        )
        
        # Сохранить SSH конфигурацию в отдельной таблице (TODO)
        # Пока просто создаем ноду
        
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
        
        return EdgeNodeStats(
            total_nodes=total,
            online_nodes=online,
            offline_nodes=offline,
            maintenance_nodes=maintenance,
            total_bandwidth=0.0,  # TODO: Calculate from analytics
            total_requests=0  # TODO: Calculate from analytics
        )
    
    @staticmethod
    async def check_node_health(node: EdgeNode) -> Dict[str, Any]:
        """Check edge node health via SSH"""
        # TODO: Implement SSH connection and health check
        # For now, return mock data
        return {
            "status": "online",
            "cpu_usage": 25.5,
            "memory_usage": 45.2,
            "disk_usage": 30.1
        }
    
    @staticmethod
    async def execute_command(
        node: EdgeNode,
        command: str,
        timeout: int = 30
    ) -> EdgeNodeCommandResult:
        """Execute command on edge node via SSH"""
        # TODO: Get SSH credentials from secure storage
        ssh_host = node.ip_address  # или из конфига
        ssh_port = 22
        ssh_user = "root"
        
        try:
            start_time = datetime.utcnow()
            
            # В реальной реализации использовать asyncssh
            # async with asyncssh.connect(
            #     ssh_host,
            #     port=ssh_port,
            #     username=ssh_user,
            #     client_keys=['path/to/key'],
            #     known_hosts=None
            # ) as conn:
            #     result = await conn.run(command, timeout=timeout)
            
            # Mock implementation
            await asyncio.sleep(0.5)
            
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            
            return EdgeNodeCommandResult(
                success=True,
                stdout="Command executed successfully (mock)",
                stderr="",
                exit_code=0,
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
        # TODO: Implement via SSH
        return EdgeComponentStatus(
            component=component,
            installed=True,
            running=True,
            version="1.0.0",
            status_text="running"
        )
    
    @staticmethod
    async def manage_component(
        node: EdgeNode,
        component: str,
        action: str
    ) -> EdgeNodeCommandResult:
        """Manage component on edge node (start, stop, restart, etc.)"""
        command_map = {
            "nginx": {
                "start": "systemctl start nginx",
                "stop": "systemctl stop nginx",
                "restart": "systemctl restart nginx",
                "reload": "nginx -s reload",
                "status": "systemctl status nginx",
                "install": "apt-get update && apt-get install -y nginx",
                "update": "apt-get update && apt-get upgrade -y nginx"
            },
            "redis": {
                "start": "systemctl start redis",
                "stop": "systemctl stop redis",
                "restart": "systemctl restart redis",
                "status": "systemctl status redis",
                "install": "apt-get update && apt-get install -y redis-server"
            },
            "certbot": {
                "install": "apt-get update && apt-get install -y certbot python3-certbot-nginx",
                "status": "certbot --version"
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
        disk_usage: Optional[float] = None
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
        await db.commit()
        return True
