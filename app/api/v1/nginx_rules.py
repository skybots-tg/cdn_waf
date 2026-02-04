"""Nginx rules API endpoints for edge nodes"""
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.schemas.nginx_rules import (
    NginxRulesConfig,
    NginxRulesUpdate,
    NginxRulesResponse,
    NginxApplyResult
)
from app.services.edge_service import EdgeNodeService
from app.services.nginx_service import NginxRulesService
from app.core.security import get_current_superuser

router = APIRouter()


@router.get("/{node_id}/nginx-rules", response_model=NginxRulesResponse)
async def get_nginx_rules(
    node_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """
    Get current Nginx rules configuration for edge node.
    
    Returns the current configuration including client limits,
    WebSocket settings, compression, caching, and security rules.
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
    
    try:
        config = await NginxRulesService.get_rules(node)
        nginx_status = await NginxRulesService.get_nginx_status(node)
        
        return NginxRulesResponse(
            node_id=node.id,
            node_name=node.name,
            config=config,
            status="active" if nginx_status.get("is_active") else "inactive"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get nginx rules: {str(e)}"
        )


@router.put("/{node_id}/nginx-rules", response_model=NginxApplyResult)
async def update_nginx_rules(
    node_id: int,
    rules: NginxRulesConfig,
    test_only: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """
    Update Nginx rules configuration on edge node.
    
    This will:
    1. Generate new nginx configuration
    2. Upload to the edge node
    3. Test the configuration (nginx -t)
    4. Reload nginx if test passes (unless test_only=true)
    
    Parameters:
    - test_only: If true, only test configuration without applying
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
    
    result = await NginxRulesService.apply_rules(node, rules, test_only=test_only)
    return result


@router.patch("/{node_id}/nginx-rules", response_model=NginxApplyResult)
async def patch_nginx_rules(
    node_id: int,
    rules: NginxRulesUpdate,
    test_only: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """
    Partially update Nginx rules configuration.
    
    Only specified sections will be updated, others remain unchanged.
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
    
    # Get current config
    current_config = await NginxRulesService.get_rules(node)
    current_dict = current_config.model_dump()
    
    # Apply updates
    update_dict = rules.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        if value is not None:
            current_dict[key] = value
    
    # Create updated config
    updated_config = NginxRulesConfig(**current_dict)
    
    result = await NginxRulesService.apply_rules(node, updated_config, test_only=test_only)
    return result


@router.get("/{node_id}/nginx-rules/defaults", response_model=NginxRulesConfig)
async def get_default_nginx_rules(
    node_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """
    Get default Nginx rules configuration.
    
    Useful for resetting to defaults or understanding available options.
    """
    node = await EdgeNodeService.get_node(db, node_id)
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Edge node not found"
        )
    
    return NginxRulesConfig()


@router.post("/{node_id}/nginx-rules/reset", response_model=NginxApplyResult)
async def reset_nginx_rules(
    node_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """
    Reset Nginx rules to default configuration.
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
    
    default_config = NginxRulesConfig()
    result = await NginxRulesService.apply_rules(node, default_config)
    return result


@router.get("/{node_id}/nginx-status", response_model=Dict[str, Any])
async def get_nginx_status(
    node_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """
    Get current Nginx service status on edge node.
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
    
    return await NginxRulesService.get_nginx_status(node)


@router.post("/{node_id}/nginx-rules/preview")
async def preview_nginx_config(
    node_id: int,
    rules: NginxRulesConfig,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """
    Preview generated Nginx configuration without applying.
    
    Returns the nginx config that would be generated from the given rules.
    """
    node = await EdgeNodeService.get_node(db, node_id)
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Edge node not found"
        )
    
    nginx_config = NginxRulesService.generate_nginx_config(rules)
    location_snippet = NginxRulesService.generate_location_snippet(rules)
    
    return {
        "main_config": nginx_config,
        "location_snippet": location_snippet
    }
