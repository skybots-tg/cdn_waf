"""DNS node background tasks"""
import asyncio
from sqlalchemy import select
from celery import shared_task
from app.tasks import celery_app
from app.core.database import async_session_maker
from app.services.dns_node_service import DNSNodeService
from app.models.dns_node import DNSNode

@celery_app.task(name="app.tasks.dns.check_dns_health")
def check_dns_health():
    """Check health of all enabled DNS nodes"""
    # Since Celery tasks are sync by default, we need to run async code
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(_check_dns_health_async())

async def _check_dns_health_async():
    """Async implementation of health check"""
    async with async_session_maker() as db:
        # Get all enabled nodes
        result = await db.execute(select(DNSNode).where(DNSNode.enabled == True))
        nodes = result.scalars().all()
        
        results = {}
        for node in nodes:
            try:
                # We reuse the check_health method which updates DB
                health = await DNSNodeService.check_health(node, db)
                results[node.name] = health["status"]
            except Exception as e:
                print(f"Error checking DNS node {node.name}: {e}")
                results[node.name] = "error"
        
        return results
