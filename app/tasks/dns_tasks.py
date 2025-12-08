"""DNS node background tasks"""
import asyncio
import dns.resolver
from sqlalchemy import select
from celery import shared_task
from app.tasks import celery_app
from app.core.database import AsyncSessionLocal as async_session_maker
from app.services.dns_node_service import DNSNodeService
from app.services.domain_service import DomainService
from app.models.dns_node import DNSNode
from app.models.domain import Domain, DomainStatus

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

@celery_app.task(name="app.tasks.dns.sync_dns_nodes")
def sync_dns_nodes():
    """Sync DNS records to all enabled nodes"""
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(_sync_dns_nodes_async())

async def _sync_dns_nodes_async():
    """Async implementation of DNS sync"""
    async with async_session_maker() as db:
        # Get all enabled nodes
        result = await db.execute(select(DNSNode).where(DNSNode.enabled == True))
        nodes = result.scalars().all()
        
        results = {}
        for node in nodes:
            try:
                # Sync database
                res = await DNSNodeService.sync_database(node, db)
                results[node.name] = "success" if res.success else f"failed: {res.stderr}"
            except Exception as e:
                print(f"Error syncing DNS node {node.name}: {e}")
                results[node.name] = f"error: {str(e)}"
        
        return results

@celery_app.task(name="app.tasks.dns.verify_pending_domains")
def verify_pending_domains():
    """Check NS records for pending domains"""
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(_verify_pending_domains_async())

async def _verify_pending_domains_async():
    """Async implementation of domain verification"""
    async with async_session_maker() as db:
        # Get all pending domains
        result = await db.execute(select(Domain).where(Domain.status == DomainStatus.PENDING))
        domains = result.scalars().all()
        
        domain_service = DomainService(db)
        results = {}
        
        # Expected nameservers (should be in config, but using defaults for now)
        EXPECTED_NS = {"ns1.flarecloud.ru", "ns2.flarecloud.ru"}
        
        for domain in domains:
            try:
                # Check NS records
                # Use Google DNS to avoid local caching issues
                resolver = dns.resolver.Resolver()
                resolver.nameservers = ['8.8.8.8', '8.8.4.4']
                
                try:
                    answers = resolver.resolve(domain.name, 'NS')
                    ns_records = {str(r.target).rstrip('.').lower() for r in answers}
                    
                    # Check if any of our nameservers are present
                    # We check if intersection is not empty, or if we want strict match?
                    # Usually, having at least one correct NS is enough to start, 
                    # but ideally all should match. Let's look for intersection.
                    if ns_records & EXPECTED_NS:
                        print(f"Domain {domain.name} verified! Found NS: {ns_records}")
                        await domain_service.verify_ns(domain)
                        results[domain.name] = "verified"
                    else:
                        print(f"Domain {domain.name} verification failed. Found NS: {ns_records}, Expected: {EXPECTED_NS}")
                        results[domain.name] = "failed"
                        
                except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.LifetimeTimeout):
                     print(f"Domain {domain.name} verification failed: No NS records found")
                     results[domain.name] = "no_records"
                     
            except Exception as e:
                print(f"Error verifying domain {domain.name}: {e}")
                results[domain.name] = f"error: {str(e)}"
        
        await db.commit()
        return results
