"""Edge node configuration tasks"""
import asyncio
import logging
from typing import Optional, Dict, Any
from celery import shared_task
from sqlalchemy import select
from app.tasks import celery_app
from app.tasks.utils import create_task_db_session

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.edge.update_edge_config")
def update_edge_config(node_id: int):
    """Bump config_version for a specific edge node so it pulls new config on next poll."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_update_edge_config_async(node_id))
    finally:
        loop.close()


async def _update_edge_config_async(node_id: int):
    from app.models.edge_node import EdgeNode
    engine, SessionLocal = create_task_db_session()
    try:
        async with SessionLocal() as db:
            result = await db.execute(select(EdgeNode).where(EdgeNode.id == node_id))
            node = result.scalar_one_or_none()
            if not node:
                logger.warning("Edge node %s not found for config update", node_id)
                return {"status": "error", "node_id": node_id, "detail": "not found"}
            node.config_version = (node.config_version or 0) + 1
            await db.commit()
            logger.info("Bumped config_version for edge node %s to %s", node_id, node.config_version)
            return {"status": "success", "node_id": node_id, "config_version": node.config_version}
    finally:
        await engine.dispose()


@celery_app.task(name="app.tasks.edge.update_all_edge_configs")
def update_all_edge_configs():
    """Bump config_version for all enabled edge nodes."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_update_all_edge_configs_async())
    finally:
        loop.close()


async def _update_all_edge_configs_async():
    from app.models.edge_node import EdgeNode
    engine, SessionLocal = create_task_db_session()
    try:
        async with SessionLocal() as db:
            result = await db.execute(select(EdgeNode).where(EdgeNode.enabled == True))
            nodes = result.scalars().all()
            for node in nodes:
                node.config_version = (node.config_version or 0) + 1
            await db.commit()
            logger.info("Bumped config_version for %d edge nodes", len(nodes))
            return {"status": "success", "updated": len(nodes)}
    finally:
        await engine.dispose()


@celery_app.task(name="app.tasks.edge.health_check_origins")
def health_check_origins():
    """Perform HTTP health checks on all origins with health_check_enabled."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_health_check_origins_async())
    finally:
        loop.close()


async def _health_check_origins_async():
    from app.models.origin import Origin
    from app.services.origin_service import OriginService
    engine, SessionLocal = create_task_db_session()
    try:
        async with SessionLocal() as db:
            result = await db.execute(
                select(Origin).where(Origin.enabled == True, Origin.health_check_enabled == True)
            )
            origins = result.scalars().all()
            checked = 0
            for origin in origins:
                try:
                    await OriginService.check_health(db, origin.id)
                    checked += 1
                except Exception as e:
                    logger.error("Health check failed for origin %s: %s", origin.id, e)
            logger.info("Completed health checks for %d origins", checked)
            return {"status": "success", "checked": checked}
    finally:
        await engine.dispose()


@celery_app.task(bind=True, name="app.tasks.edge.run_node_component")
def run_node_component_task(
    self,
    node_id: int,
    component: str,
    action: str,
    node_type: str = "edge",  # "edge" or "dns"
    params: Optional[Dict[str, Any]] = None
):
    """
    Run component action on edge or DNS node asynchronously.
    
    Args:
        node_id: Node ID
        component: Component name (nginx, python, agent, system, certbot)
        action: Action to perform (install, update, start, stop, etc.)
        node_type: Type of node - "edge" or "dns"
        params: Additional parameters
    
    Returns:
        dict with success, stdout, stderr, exit_code, execution_time
    """
    logger.info(f"Starting {node_type} node task: node_id={node_id}, component={component}, action={action}")
    
    # Update state to show we're starting
    self.update_state(
        state='PROGRESS',
        meta={'progress': f'Starting {action} for {component}...', 'node_id': node_id}
    )
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(
            _run_node_component_async(self, node_id, component, action, node_type, params)
        )
        return result
    finally:
        loop.close()


async def _run_node_component_async(
    task,
    node_id: int,
    component: str,
    action: str,
    node_type: str,
    params: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Async implementation of node component task"""
    
    # Create a fresh engine and session factory for this task's event loop
    engine, SessionLocal = create_task_db_session()
    
    try:
        async with SessionLocal() as db:
            try:
                if node_type == "edge":
                    from app.models.edge_node import EdgeNode
                    from app.services.edge_service import EdgeNodeService
                    
                    result = await db.execute(select(EdgeNode).where(EdgeNode.id == node_id))
                    node = result.scalar_one_or_none()
                    
                    if not node:
                        return {
                            "success": False,
                            "stdout": "",
                            "stderr": f"Edge node {node_id} not found",
                            "exit_code": 1,
                            "execution_time": 0
                        }
                    
                    task.update_state(
                        state='PROGRESS',
                        meta={'progress': f'Connecting to {node.name} ({node.ip_address})...', 'node_id': node_id}
                    )
                    
                    # Run the actual command
                    cmd_result = await EdgeNodeService.manage_component(
                        node, component, action, params
                    )
                    
                else:  # dns node
                    from app.models.dns_node import DNSNode
                    from app.services.dns_node_service import DNSNodeService
                    
                    result = await db.execute(select(DNSNode).where(DNSNode.id == node_id))
                    node = result.scalar_one_or_none()
                    
                    if not node:
                        return {
                            "success": False,
                            "stdout": "",
                            "stderr": f"DNS node {node_id} not found",
                            "exit_code": 1,
                            "execution_time": 0
                        }
                    
                    task.update_state(
                        state='PROGRESS',
                        meta={'progress': f'Connecting to {node.name} ({node.ip_address})...', 'node_id': node_id}
                    )
                    
                    # Run the actual command
                    cmd_result = await DNSNodeService.manage_component_action(
                        node, component, action, db
                    )
                
                # Convert result to dict
                return {
                    "success": cmd_result.success,
                    "stdout": cmd_result.stdout,
                    "stderr": cmd_result.stderr,
                    "exit_code": cmd_result.exit_code,
                    "execution_time": cmd_result.execution_time
                }
                
            except Exception as e:
                logger.error(f"Task failed for {node_type} node {node_id}: {e}", exc_info=True)
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": str(e),
                    "exit_code": 1,
                    "execution_time": 0
                }
    finally:
        # Clean up the engine to release connections
        await engine.dispose()


