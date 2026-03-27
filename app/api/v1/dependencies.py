"""Shared API dependencies to eliminate repeated patterns across endpoints"""
from typing import Optional, Set
from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.domain import Domain
from app.models.user import User
from app.models.organization import Organization, OrganizationMember


async def get_domain_or_404(
    domain_id: int,
    db: AsyncSession,
) -> Domain:
    """Fetch domain by ID or raise 404. Eliminates the repeated pattern across endpoints."""
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    if not domain:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domain not found",
        )
    return domain


async def get_user_org_ids(
    user: User,
    db: AsyncSession,
) -> Set[int]:
    """
    Get all organization IDs the user belongs to (owned + member + default).
    Eliminates triple-duplicated org query in auth.py.
    """
    owned_result = await db.execute(
        select(Organization.id).where(Organization.owner_id == user.id)
    )
    owned = {row[0] for row in owned_result.fetchall()}

    member_result = await db.execute(
        select(OrganizationMember.organization_id)
        .where(OrganizationMember.user_id == user.id)
    )
    members = {row[0] for row in member_result.fetchall()}

    org_ids = owned | members
    org_ids.add(1)
    return org_ids
