"""DNS Nodes API"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_active_user, get_current_superuser
from app.models.user import User
from app.schemas.dns_node import (
    DNSNodeCreate,
    DNSNodeUpdate,
    DNSNodeResponse,
    DNSNodeStats,
    DNSNodeCommand,
    DNSNodeCommandResult,
    DNSComponentAction,
    DNSComponentStatus
)
from app.services.dns_node_service import DNSNodeService

router = APIRouter()

@router.get("/", response_model=List[DNSNodeResponse])
async def list_dns_nodes(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    location: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """List all DNS nodes"""
    return await DNSNodeService.get_nodes(db, skip, limit, status, location)

@router.get("/stats", response_model=DNSNodeStats)
async def get_dns_nodes_stats(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get DNS nodes statistics"""
    return await DNSNodeService.get_stats(db)

@router.post("/", response_model=DNSNodeResponse, status_code=status.HTTP_201_CREATED)
async def create_dns_node(
    node_create: DNSNodeCreate,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Create new DNS node"""
    return await DNSNodeService.create_node(db, node_create)

@router.get("/{node_id}", response_model=DNSNodeResponse)
async def get_dns_node(
    node_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get DNS node by ID"""
    node = await DNSNodeService.get_node(db, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node

@router.patch("/{node_id}", response_model=DNSNodeResponse)
async def update_dns_node(
    node_id: int,
    node_update: DNSNodeUpdate,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Update DNS node"""
    node = await DNSNodeService.update_node(db, node_id, node_update)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node

@router.delete("/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dns_node(
    node_id: int,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Delete DNS node"""
    if not await DNSNodeService.delete_node(db, node_id):
        raise HTTPException(status_code=404, detail="Node not found")

@router.post("/{node_id}/component", response_model=DNSNodeCommandResult)
async def manage_component(
    node_id: int,
    action: DNSComponentAction,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Manage DNS node component"""
    node = await DNSNodeService.get_node(db, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
        
    return await DNSNodeService.manage_component_action(node, action.component, action.action, db)

@router.post("/{node_id}/command", response_model=DNSNodeCommandResult)
async def execute_command(
    node_id: int,
    command: DNSNodeCommand,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Execute arbitrary command on node"""
    node = await DNSNodeService.get_node(db, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    return await DNSNodeService.execute_command(node, command.command, command.timeout)

@router.get("/{node_id}/logs")
async def get_node_logs(
    node_id: int,
    lines: int = 100,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get DNS node logs"""
    node = await DNSNodeService.get_node(db, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    logs = await DNSNodeService.get_logs(node, lines)
    return {"logs": logs}

@router.get("/{node_id}/components/{component}", response_model=DNSComponentStatus)
async def get_component_status(
    node_id: int,
    component: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get status of a component"""
    node = await DNSNodeService.get_node(db, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    return await DNSNodeService.get_component_status(node, component)

@router.post("/{node_id}/check-health")
async def check_node_health(
    node_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Check node health and update status"""
    node = await DNSNodeService.get_node(db, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    return await DNSNodeService.check_health(node, db)
