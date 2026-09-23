"""DNS endpoints"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import get_current_active_user
from app.schemas.dns import DNSRecordCreate, DNSRecordUpdate, DNSRecordResponse, DNSRecordImport
from app.schemas.validators import proxy_refusal
from app.models.user import User
from app.models.dns import DNSRecord
from app.models.domain import Domain
from app.tasks.dns_tasks import sync_dns_nodes
from app.api.v1.dependencies import get_domain_or_404, get_domain_for_user, get_dns_record_for_user

router = APIRouter()


@router.get("/domains/{domain_id}/records", response_model=List[DNSRecordResponse])
async def list_dns_records(
    domain_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    domain: Domain = Depends(get_domain_for_user)
):
    """List all DNS records for domain"""
    result = await db.execute(
        select(DNSRecord)
        .where(DNSRecord.domain_id == domain_id)
        .order_by(DNSRecord.name, DNSRecord.type)
    )
    records = list(result.scalars().all())
    return records


@router.post("/domains/{domain_id}/records", response_model=DNSRecordResponse, status_code=status.HTTP_201_CREATED)
async def create_dns_record(
    domain_id: int,
    record_create: DNSRecordCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    domain: Domain = Depends(get_domain_for_user)
):
    """Create DNS record"""
    # Verify domain exists
    domain = await get_domain_or_404(domain_id, db)
    
    # Normalize record name
    # If name is absolute (ends with domain name), make it relative
    name = record_create.name.lower()
    domain_name = domain.name.lower()
    
    if name == domain_name:
        name = "@"
    elif name.endswith(f".{domain_name}"):
        name = name[:-len(domain_name)-1]
    
    # Create record
    record_data = record_create.model_dump()
    record_data["name"] = name
    
    record = DNSRecord(
        domain_id=domain_id,
        **record_data
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    
    # Trigger sync to DNS nodes
    sync_dns_nodes.delay()
    
    return record


@router.post("/domains/{domain_id}/records/import", status_code=status.HTTP_201_CREATED)
async def import_dns_records(
    domain_id: int,
    import_data: DNSRecordImport,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    domain: Domain = Depends(get_domain_for_user)
):
    """Import DNS records"""
    # Verify domain exists
    domain = await get_domain_or_404(domain_id, db)
    
    count = 0
    domain_name = domain.name.lower()
    
    for record_data in import_data.records:
        # Normalize name
        name = record_data.name.lower()
        if name == domain_name:
            name = "@"
        elif name.endswith(f".{domain_name}"):
            name = name[:-len(domain_name)-1]
            
        data = record_data.model_dump()
        data["name"] = name
        
        record = DNSRecord(
            domain_id=domain_id,
            **data
        )
        db.add(record)
        count += 1
    
    await db.commit()
    
    # Trigger sync to DNS nodes
    if count > 0:
        sync_dns_nodes.delay()
        
    return {"message": f"Imported {count} records", "count": count}


@router.get("/records/{record_id}", response_model=DNSRecordResponse)
async def get_dns_record(
    record_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    record: DNSRecord = Depends(get_dns_record_for_user)
):
    """Get DNS record by ID"""
    result = await db.execute(
        select(DNSRecord).where(DNSRecord.id == record_id)
    )
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="DNS record not found"
        )

    return record


@router.patch("/records/{record_id}", response_model=DNSRecordResponse)
async def update_dns_record(
    record_id: int,
    record_update: DNSRecordUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    record: DNSRecord = Depends(get_dns_record_for_user)
):
    """Update DNS record"""
    result = await db.execute(
        select(DNSRecord).where(DNSRecord.id == record_id)
    )
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="DNS record not found"
        )

    # Update fields
    update_data = record_update.model_dump(exclude_unset=True)
    
    # Filter out None values to prevent NULL constraint violations
    update_data = {k: v for k, v in update_data.items() if v is not None}
    
    # Normalize name if present
    if "name" in update_data:
        # We need domain to normalize
        domain_result = await db.execute(select(Domain).where(Domain.id == record.domain_id))
        domain = domain_result.scalar_one_or_none()
        
        if domain:
             name = update_data["name"].lower()
             domain_name = domain.name.lower()
             if name == domain_name:
                 update_data["name"] = "@"
             elif name.endswith(f".{domain_name}"):
                 update_data["name"] = name[:-len(domain_name)-1]
             else:
                 update_data["name"] = name

    for field, value in update_data.items():
        setattr(record, field, value)

    refusal = proxy_refusal(record.name, record.type) if record.proxied else None
    if refusal:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=refusal)
    
    await db.commit()
    await db.refresh(record)
    
    # Trigger sync to DNS nodes
    sync_dns_nodes.delay()
    
    return record


@router.delete("/records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dns_record(
    record_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    record: DNSRecord = Depends(get_dns_record_for_user)
):
    """Delete DNS record"""
    result = await db.execute(
        select(DNSRecord).where(DNSRecord.id == record_id)
    )
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="DNS record not found"
        )

    await db.delete(record)
    await db.commit()
    
    # Trigger sync to DNS nodes
    sync_dns_nodes.delay()
