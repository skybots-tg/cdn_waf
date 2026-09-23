"""Shared API dependencies to eliminate repeated patterns across endpoints.

The ``get_*_for_user`` dependencies below are the single place tenant isolation
is enforced: every domain-scoped and child-resource route resolves its object
through one of them, which checks that the object's domain belongs to an
organization the caller is a member of (404 on mismatch, so ids can't be probed)
and then applies API-token domain scoping via ``require_domain_access``.
"""
from typing import List, Optional, Set
from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_active_user, require_domain_access
from app.models.domain import Domain
from app.models.user import User
from app.models.organization import Organization, OrganizationMember, OrganizationRole
from app.models.origin import Origin
from app.models.cache import CacheRule
from app.models.waf import WAFRule, RateLimit, IPAccessRule
from app.models.dns import DNSRecord
from app.models.certificate import Certificate


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
    """Return every organization id the user owns or is a member of.

    Superusers see everything, so callers that need a "can this user touch this
    org" answer should also honour ``user.is_superuser`` (see ``_assert_org``).
    Note: there is deliberately no implicit org ``1`` here — that was the bug
    that funnelled every tenant into a single shared organization.
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

    return owned | members


async def visible_domain_ids(user: User, db: AsyncSession) -> Optional[List[int]]:
    """Домены, чью аналитику видит пользователь; ``None`` — все.

    Суперпользователь видит всё (если его API-токен не ограничен доменами),
    остальные — домены своих организаций. Раньше общая аналитика была только
    для суперпользователя, и у остальных все карточки показывали 403 как нули.
    """
    from app.core.security import get_allowed_domain_ids

    allowed = get_allowed_domain_ids(user)
    if user.is_superuser:
        return None if allowed is None else sorted(allowed)
    org_ids = await get_user_org_ids(user, db)
    if not org_ids:
        return []
    ids = [
        row[0] for row in (await db.execute(
            select(Domain.id).where(Domain.organization_id.in_(org_ids))
        )).all()
    ]
    if allowed is not None:
        ids = [i for i in ids if i in allowed]
    return ids


async def get_or_create_primary_org(user: User, db: AsyncSession) -> int:
    """Return the organization new domains should be created in for ``user``.

    Prefers an org the user owns; otherwise any org they belong to; otherwise
    creates a personal organization. This replaces the old ``min(org_ids)`` /
    implicit-org-1 logic that put every tenant's domains in one shared org.
    """
    owned = await db.execute(
        select(Organization.id).where(Organization.owner_id == user.id).order_by(Organization.id)
    )
    owned_ids = [row[0] for row in owned.fetchall()]
    if owned_ids:
        return owned_ids[0]

    member = await db.execute(
        select(OrganizationMember.organization_id)
        .where(OrganizationMember.user_id == user.id)
        .order_by(OrganizationMember.organization_id)
    )
    member_ids = [row[0] for row in member.fetchall()]
    if member_ids:
        return member_ids[0]

    org = Organization(name=f"{user.email}'s organization", owner_id=user.id)
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=OrganizationRole.OWNER))
    await db.flush()
    return org.id


async def _assert_domain_access(domain: Domain, user: User, db: AsyncSession) -> Domain:
    """Raise 404 unless the user (or a superuser) may access ``domain``."""
    if not user.is_superuser:
        org_ids = await get_user_org_ids(user, db)
        if domain.organization_id not in org_ids:
            # 404 rather than 403 so a caller can't enumerate which ids exist.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Domain not found",
            )
    # API-token domain scoping (no-op for JWT users / unrestricted tokens).
    require_domain_access(user, domain.id)
    return domain


async def get_domain_for_user(
    domain_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Domain:
    """Resolve ``{domain_id}`` and assert the caller may access it."""
    domain = await get_domain_or_404(domain_id, db)
    return await _assert_domain_access(domain, user, db)


async def _get_owned_child(model, child_id: int, user: User, db: AsyncSession):
    """Load a domain-scoped child row and assert access to its parent domain."""
    result = await db.execute(select(model).where(model.id == child_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{model.__name__} not found",
        )
    domain = await get_domain_or_404(obj.domain_id, db)
    await _assert_domain_access(domain, user, db)
    return obj


# --- Child-resource dependencies (parameter names match the route path params) ---

async def get_origin_for_user(
    origin_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Origin:
    return await _get_owned_child(Origin, origin_id, user, db)


async def get_cache_rule_for_user(
    rule_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> CacheRule:
    return await _get_owned_child(CacheRule, rule_id, user, db)


async def get_waf_rule_for_user(
    rule_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> WAFRule:
    return await _get_owned_child(WAFRule, rule_id, user, db)


async def get_rate_limit_for_user(
    limit_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> RateLimit:
    return await _get_owned_child(RateLimit, limit_id, user, db)


async def get_ip_rule_for_user(
    rule_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> IPAccessRule:
    return await _get_owned_child(IPAccessRule, rule_id, user, db)


async def get_dns_record_for_user(
    record_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> DNSRecord:
    return await _get_owned_child(DNSRecord, record_id, user, db)


async def get_certificate_for_user(
    cert_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Certificate:
    return await _get_owned_child(Certificate, cert_id, user, db)
