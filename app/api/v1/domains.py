"""Domain endpoints"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
import dns.resolver
import dns.exception

from app.core.database import get_db
from app.core.security import get_current_active_user, get_optional_current_user
from app.schemas.domain import (
    DomainCreate,
    DomainUpdate,
    DomainResponse,
    DomainTLSSettingsUpdate,
    DomainTLSSettingsResponse,
)
from app.services.domain_service import DomainService
from app.models.user import User
from app.models.domain import Domain

router = APIRouter()


@router.get("/scan-dns")
async def scan_dns_records(
    domain: str = Query(..., description="Domain name to scan"),
    current_user: User = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Scan existing DNS records for a domain
    
    This endpoint queries public DNS servers to get existing records.
    """
    records = []
    record_types = ['A', 'AAAA', 'MX', 'TXT', 'CNAME', 'NS']
    
    resolver = dns.resolver.Resolver()
    resolver.timeout = 5
    resolver.lifetime = 5
    
    for record_type in record_types:
        try:
            answers = resolver.resolve(domain, record_type)
            for rdata in answers:
                record = {
                    'type': record_type,
                    'name': '@',
                    'ttl': answers.rrset.ttl,
                    'proxied': record_type in ['A', 'AAAA', 'CNAME']  # Proxy HTTP(S) records by default
                }
                
                if record_type == 'A':
                    record['content'] = str(rdata)
                elif record_type == 'AAAA':
                    record['content'] = str(rdata)
                elif record_type == 'CNAME':
                    record['content'] = str(rdata).rstrip('.')
                elif record_type == 'MX':
                    record['content'] = str(rdata.exchange).rstrip('.')
                    record['priority'] = rdata.preference
                elif record_type == 'TXT':
                    record['content'] = ' '.join([s.decode() if isinstance(s, bytes) else s for s in rdata.strings])
                elif record_type == 'NS':
                    record['content'] = str(rdata).rstrip('.')
                    record['proxied'] = False
                
                records.append(record)
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers, dns.exception.Timeout):
            # Record type doesn't exist or timeout
            continue
        except Exception as e:
            # Log error but continue
            print(f"Error resolving {record_type} for {domain}: {e}")
            continue
    
    # Also try to get www subdomain
    try:
        www_domain = f"www.{domain}"
        answers = resolver.resolve(www_domain, 'A')
        for rdata in answers:
            records.append({
                'type': 'A',
                'name': 'www',
                'content': str(rdata),
                'ttl': answers.rrset.ttl,
                'proxied': True
            })
    except:
        pass
    
    return records


@router.get("/", response_model=List[DomainResponse])
async def list_domains(
    current_user: User = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all domains for current user's organization"""
    # If no user, return empty list
    if not current_user:
        return []
    
    # TODO: Get organization_id from current user's context
    # For now, assume organization_id = 1
    organization_id = 1
    
    domain_service = DomainService(db)
    domains = await domain_service.list_by_organization(organization_id)
    return domains


@router.post("/", response_model=DomainResponse, status_code=status.HTTP_201_CREATED)
async def create_domain(
    domain_create: DomainCreate,
    current_user: User = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create new domain"""
    if not current_user:
        # For development, allow domain creation without auth
        # TODO: Require authentication in production
        pass
    
    # TODO: Get organization_id from current user's context
    organization_id = 1
    
    domain_service = DomainService(db)
    
    # Check if domain already exists
    existing_domain = await domain_service.get_by_name(domain_create.name)
    if existing_domain:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Domain already exists"
        )
    
    # Create domain
    domain = await domain_service.create(organization_id, domain_create)
    await db.commit()
    
    return domain


@router.get("/{domain_id}", response_model=DomainResponse)
async def get_domain(
    domain_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get domain by ID"""
    domain_service = DomainService(db)
    domain = await domain_service.get_by_id(domain_id)
    
    if not domain:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domain not found"
        )
    
    # TODO: Check if user has access to this domain
    
    return domain


@router.patch("/{domain_id}", response_model=DomainResponse)
async def update_domain(
    domain_id: int,
    domain_update: DomainUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Update domain"""
    domain_service = DomainService(db)
    domain = await domain_service.get_by_id(domain_id)
    
    if not domain:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domain not found"
        )
    
    # TODO: Check if user has access to this domain
    
    domain = await domain_service.update(domain, domain_update)
    await db.commit()
    
    return domain


@router.post("/{domain_id}/verify-ns")
async def verify_ns(
    domain_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Verify NS records for domain"""
    domain_service = DomainService(db)
    domain = await domain_service.get_by_id(domain_id)
    
    if not domain:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domain not found"
        )
    
    # TODO: Check if user has access to this domain
    
    verified = await domain_service.verify_ns(domain)
    await db.commit()
    
    return {"verified": verified, "domain_id": domain_id}


