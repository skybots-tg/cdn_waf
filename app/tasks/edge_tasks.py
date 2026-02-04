"""Edge node configuration tasks"""
import asyncio
import logging
from typing import Optional, Dict, Any
from celery import shared_task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.tasks import celery_app
from app.core.config import settings

logger = logging.getLogger(__name__)


def create_task_db_session():
    """
    Create a new database engine and session factory for use in Celery tasks.
    
    Each Celery task runs in its own process/thread with its own event loop,
    so we need to create a fresh engine that's bound to the current event loop.
    This avoids "Future attached to a different loop" and concurrent operation errors.
    """
    engine = create_async_engine(
        str(settings.DATABASE_URL),
        pool_size=5,
        max_overflow=10,
        echo=settings.DEBUG,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    return engine, session_factory


@celery_app.task(name="app.tasks.edge.update_edge_config")
def update_edge_config(node_id: int):
    """Update configuration for specific edge node"""
    # TODO: Implement edge node config update
    print(f"Updating config for edge node {node_id}")
    return {"status": "success", "node_id": node_id}


@celery_app.task(name="app.tasks.edge.update_all_edge_configs")
def update_all_edge_configs():
    """Update configuration for all edge nodes"""
    # TODO: Implement edge node config update for all nodes
    print("Updating config for all edge nodes")
    return {"status": "success", "updated": 0}


@celery_app.task(name="app.tasks.edge.health_check_origins")
def health_check_origins():
    """Perform health checks on all origins"""
    # TODO: Implement origin health checking
    print("Checking origin health")
    return {"status": "success", "checked": 0}


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


