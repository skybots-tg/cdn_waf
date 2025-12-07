"""Domain endpoints"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_active_user
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


@router.get("/", response_model=List[DomainResponse])
async def list_domains(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """List all domains for current user's organization"""
    # TODO: Get organization_id from current user's context
    # For now, assume organization_id = 1
    organization_id = 1
    
    domain_service = DomainService(db)
    domains = await domain_service.list_by_organization(organization_id)
    return domains


@router.post("/", response_model=DomainResponse, status_code=status.HTTP_201_CREATED)
async def create_domain(
    domain_create: DomainCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Create new domain"""
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


