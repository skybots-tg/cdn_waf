"""DNS node background tasks"""
import asyncio
import logging
import dns.resolver
from sqlalchemy import select
from celery import shared_task
from app.tasks import celery_app
from app.tasks.utils import create_task_db_session
from app.core.config import settings
from app.services.dns_node_service import DNSNodeService
from app.services.domain_service import DomainService
from app.models.dns_node import DNSNode
from app.models.domain import Domain, DomainStatus

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.dns.check_dns_health")
def check_dns_health():
    """Check health of all enabled DNS nodes"""
    return asyncio.run(_check_dns_health_async())

async def _check_dns_health_async():
    """Async implementation of health check"""
    engine, SessionLocal = create_task_db_session()
    try:
        async with SessionLocal() as db:
            result = await db.execute(select(DNSNode).where(DNSNode.enabled == True))
            nodes = result.scalars().all()
            
            results = {}
            for node in nodes:
                try:
                    health = await DNSNodeService.check_health(node, db)
                    results[node.name] = health["status"]
                except Exception as e:
                    logger.error("Error checking DNS node %s: %s", node.name, e)
                    results[node.name] = "error"
            
            return results
    finally:
        await engine.dispose()

@celery_app.task(name="app.tasks.dns.sync_dns_nodes")
def sync_dns_nodes():
    """Sync DNS records to all enabled nodes"""
    return asyncio.run(_sync_dns_nodes_async())

async def _sync_dns_nodes_async():
    """Async implementation of DNS sync"""
    engine, SessionLocal = create_task_db_session()
    try:
        async with SessionLocal() as db:
            result = await db.execute(select(DNSNode).where(DNSNode.enabled == True))
            nodes = result.scalars().all()
            
            results = {}
            for node in nodes:
                try:
                    res = await DNSNodeService.sync_database(node, db)
                    results[node.name] = "success" if res.success else f"failed: {res.stderr}"
                except Exception as e:
                    logger.error("Error syncing DNS node %s: %s", node.name, e)
                    results[node.name] = f"error: {str(e)}"
            
            return results
    finally:
        await engine.dispose()

@celery_app.task(name="app.tasks.dns.verify_pending_domains")
def verify_pending_domains():
    """Check NS records for pending domains"""
    return asyncio.run(_verify_pending_domains_async())

async def _verify_pending_domains_async():
    """Async implementation of domain verification"""
    engine, SessionLocal = create_task_db_session()
    try:
        async with SessionLocal() as db:
            result = await db.execute(select(Domain).where(Domain.status == DomainStatus.PENDING))
            domains = result.scalars().all()
            
            domain_service = DomainService(db)
            results = {}
            
            expected_ns = {
                ns.strip().lower()
                for ns in settings.EXPECTED_NS.split(",")
            }
            resolvers = [r.strip() for r in settings.DNS_RESOLVERS.split(",")]
            
            for domain in domains:
                try:
                    resolver = dns.resolver.Resolver()
                    resolver.nameservers = resolvers
                    
                    try:
                        answers = resolver.resolve(domain.name, 'NS')
                        ns_records = {str(r.target).rstrip('.').lower() for r in answers}
                        
                        if ns_records & expected_ns:
                            logger.info("Domain %s verified! Found NS: %s", domain.name, ns_records)
                            await domain_service.verify_ns(domain)
                            results[domain.name] = "verified"
                        else:
                            logger.debug(
                                "Domain %s verification failed. Found NS: %s, Expected: %s",
                                domain.name, ns_records, expected_ns,
                            )
                            results[domain.name] = "failed"
                            
                    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.LifetimeTimeout):
                         logger.debug("Domain %s: no NS records found", domain.name)
                         results[domain.name] = "no_records"
                         
                except Exception as e:
                    logger.error("Error verifying domain %s: %s", domain.name, e)
                    results[domain.name] = f"error: {str(e)}"
            
            await db.commit()
            return results
    finally:
        await engine.dispose()
