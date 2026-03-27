"""Domain service"""
import logging
from typing import Optional, List
import secrets
import dns.exception
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.domain import Domain, DomainTLSSettings, DomainStatus
from app.models.organization import Organization
from app.schemas.domain import DomainCreate, DomainUpdate

logger = logging.getLogger(__name__)


class DomainService:
    """Domain service for database operations"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_by_id(self, domain_id: int) -> Optional[Domain]:
        """Get domain by ID"""
        result = await self.db.execute(
            select(Domain)
            .options(selectinload(Domain.tls_settings))
            .where(Domain.id == domain_id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_name(self, name: str) -> Optional[Domain]:
        """Get domain by name"""
        result = await self.db.execute(
            select(Domain).where(Domain.name == name)
        )
        return result.scalar_one_or_none()
    
    async def list_by_organization(self, organization_id: int) -> List[Domain]:
        """List domains by organization"""
        result = await self.db.execute(
            select(Domain)
            .where(Domain.organization_id == organization_id)
            .order_by(Domain.created_at.desc())
        )
        return list(result.scalars().all())
    
    async def create(self, organization_id: int, domain_create: DomainCreate) -> Domain:
        """Create new domain"""
        # Generate verification token
        verification_token = secrets.token_urlsafe(32)
        
        domain = Domain(
            organization_id=organization_id,
            name=domain_create.name.lower(),
            status=DomainStatus.PENDING,
            verification_token=verification_token,
        )
        self.db.add(domain)
        await self.db.flush()
        
        # Create default TLS settings
        tls_settings = DomainTLSSettings(domain_id=domain.id)
        self.db.add(tls_settings)
        await self.db.flush()
        
        await self.db.refresh(domain)
        return domain
    
    async def update(self, domain: Domain, domain_update: DomainUpdate) -> Domain:
        """Update domain"""
        if domain_update.status is not None:
            domain.status = domain_update.status
        
        await self.db.flush()
        await self.db.refresh(domain)
        return domain
    
    async def verify_ns(self, domain: Domain) -> bool:
        """Verify NS records point to our nameservers."""
        import dns.resolver
        from datetime import datetime
        from app.core.config import settings

        expected_ns = set()
        for ns in getattr(settings, "EXPECTED_NS", "ns1.flarecloud.ru,ns2.flarecloud.ru").split(","):
            expected_ns.add(ns.strip().lower())

        resolver = dns.resolver.Resolver()
        resolver.nameservers = ["8.8.8.8", "8.8.4.4"]
        resolver.timeout = 5
        resolver.lifetime = 5

        try:
            answers = resolver.resolve(domain.name, "NS")
            found_ns = {str(r.target).rstrip(".").lower() for r in answers}
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer,
                dns.resolver.NoNameservers, dns.exception.Timeout):
            return False
        except Exception:
            return False

        if found_ns & expected_ns:
            domain.ns_verified = True
            domain.ns_verified_at = datetime.utcnow()
            domain.status = DomainStatus.ACTIVE
            await self.db.flush()
            return True
        return False
    
    async def delete(self, domain: Domain) -> None:
        """Delete domain and all related records (cascades)"""
        await self.db.delete(domain)
        await self.db.flush()
