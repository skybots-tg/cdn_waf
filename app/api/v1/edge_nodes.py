"""Edge nodes API endpoints"""
from typing import List, Optional, Dict, Union
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.schemas.edge_node import (
    EdgeNodeCreate,
    EdgeNodeUpdate,
    EdgeNodeResponse,
    EdgeNodeStats,
    EdgeNodeCommand,
    EdgeNodeCommandResult,
    EdgeComponentAction,
    EdgeComponentStatus
)
from app.schemas.task import TaskStartResponse
from app.services.edge_service import EdgeNodeService
from app.core.security import get_current_superuser
from app.tasks.edge_tasks import run_node_component_task

router = APIRouter()

# Actions that should run asynchronously (long-running operations)
ASYNC_ACTIONS = {'install', 'update'}


@router.get("/stats", response_model=EdgeNodeStats)
async def get_edge_nodes_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """Get edge nodes statistics (superuser only)"""
    return await EdgeNodeService.get_stats(db)


@router.get("/", response_model=List[EdgeNodeResponse])
async def get_edge_nodes(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    location: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """
    Get list of edge nodes (superuser only)
    
    Filters:
    - status: online, offline, maintenance
    - location: location code (RU-MSK, RU-SPB, etc.)
    """
    nodes = await EdgeNodeService.get_nodes(db, skip, limit, status, location)
    return nodes


@router.get("/{node_id}", response_model=EdgeNodeResponse)
async def get_edge_node(
    node_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """Get edge node by ID (superuser only)"""
    node = await EdgeNodeService.get_node(db, node_id)
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Edge node not found"
        )
    return node


@router.post("/", response_model=EdgeNodeResponse, status_code=status.HTTP_201_CREATED)
async def create_edge_node(
    node_data: EdgeNodeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """Create new edge node (superuser only)"""
    # Check if name already exists
    existing = await EdgeNodeService.get_node_by_name(db, node_data.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Edge node with this name already exists"
        )
    
    node = await EdgeNodeService.create_node(db, node_data)
    return node


@router.patch("/{node_id}", response_model=EdgeNodeResponse)
async def update_edge_node(
    node_id: int,
    node_data: EdgeNodeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """Update edge node (superuser only)"""
    node = await EdgeNodeService.update_node(db, node_id, node_data)
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Edge node not found"
        )
    return node


@router.delete("/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_edge_node(
    node_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """Delete edge node (superuser only)"""
    try:
        success = await EdgeNodeService.delete_node(db, node_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Edge node not found"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete edge node: {str(e)}"
        )


@router.post("/{node_id}/regenerate-api-key", response_model=Dict[str, str])
async def regenerate_node_api_key(
    node_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """Regenerate API key for edge node (superuser only)"""
    new_key = await EdgeNodeService.regenerate_api_key(db, node_id)
    if not new_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Edge node not found"
        )
    return {"api_key": new_key}


@router.post("/{node_id}/command", response_model=EdgeNodeCommandResult)
async def execute_node_command(
    node_id: int,
    command_data: EdgeNodeCommand,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """Execute command on edge node via SSH (superuser only)"""
    node = await EdgeNodeService.get_node(db, node_id)
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Edge node not found"
        )
    
    if not node.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Edge node is disabled"
        )
    
    result = await EdgeNodeService.execute_command(
        node,
        command_data.command,
        command_data.timeout
    )
    return result


@router.get("/{node_id}/component/{component}", response_model=EdgeComponentStatus)
async def get_component_status(
    node_id: int,
    component: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """Get status of component on edge node (superuser only)"""
    node = await EdgeNodeService.get_node(db, node_id)
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Edge node not found"
        )
    
    status = await EdgeNodeService.get_component_status(node, component)
    return status


@router.post("/{node_id}/component", response_model=Union[EdgeNodeCommandResult, TaskStartResponse])
async def manage_component(
    node_id: int,
    action_data: EdgeComponentAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """
    Manage component on edge node (superuser only)
    
    Supported components: nginx, redis, certbot, python, agent, system
    Supported actions: start, stop, restart, reload, status, install, update
    
    Long-running actions (install, update) run asynchronously and return task_id.
    Use GET /api/v1/tasks/{task_id} to check status.
    """
    node = await EdgeNodeService.get_node(db, node_id)
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Edge node not found"
        )
    
    if not node.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Edge node is disabled"
        )
    
    # Check if this is a long-running action
    if action_data.action in ASYNC_ACTIONS:
        # Start async task
        task = run_node_component_task.delay(
            node_id=node_id,
            component=action_data.component,
            action=action_data.action,
            node_type="edge",
            params=action_data.params
        )
        return TaskStartResponse(
            task_id=task.id,
            status="PENDING",
            message=f"Started {action_data.action} for {action_data.component}"
        )
    
    # For quick actions, run synchronously
    result = await EdgeNodeService.manage_component(
        node,
        action_data.component,
        action_data.action,
        params=action_data.params
    )
    return result


@router.post("/{node_id}/health-check")
async def check_node_health(
    node_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """Check edge node health (superuser only)"""
    node = await EdgeNodeService.get_node(db, node_id)
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Edge node not found"
        )
    
    health = await EdgeNodeService.check_node_health(node)
    
    # Update metrics in database
    await EdgeNodeService.update_metrics(
        db,
        node_id,
        cpu_usage=health.get("cpu_usage"),
        memory_usage=health.get("memory_usage"),
        disk_usage=health.get("disk_usage"),
        status=health.get("status", "unknown")
    )
    
    return health
