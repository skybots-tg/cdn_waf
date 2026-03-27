"""Organization management endpoints"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import get_current_active_user
from app.models.user import User
from app.models.organization import Organization, OrganizationMember, OrganizationRole
from app.api.v1.dependencies import get_user_org_ids

logger = logging.getLogger(__name__)

router = APIRouter()


class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: str = "member"


@router.get("/members")
async def get_organization_members(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all members of user's organization."""
    result = await db.execute(
        select(OrganizationMember)
        .where(OrganizationMember.user_id == current_user.id)
    )
    membership = result.scalar_one_or_none()

    if not membership:
        return []

    result = await db.execute(
        select(OrganizationMember, User)
        .join(User, OrganizationMember.user_id == User.id)
        .where(OrganizationMember.organization_id == membership.organization_id)
    )
    members_data = result.all()

    return [
        {
            "id": member.id,
            "user_id": member.user_id,
            "email": user.email,
            "role": member.role.value,
            "created_at": member.invited_at.isoformat() if member.invited_at else None,
        }
        for member, user in members_data
    ]


@router.post("/members/invite")
async def invite_member(
    body: InviteMemberRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Invite a user to the current user's organization."""
    my_membership = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.role.in_([OrganizationRole.OWNER, OrganizationRole.ADMIN]),
        )
    )
    membership = my_membership.scalar_one_or_none()

    if not membership:
        org_result = await db.execute(
            select(Organization).where(Organization.owner_id == current_user.id)
        )
        org = org_result.scalar_one_or_none()
        if not org:
            raise HTTPException(status_code=403, detail="Not an admin of any organization")
        org_id = org.id
    else:
        org_id = membership.organization_id

    target_user_result = await db.execute(select(User).where(User.email == body.email))
    target_user = target_user_result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User with this email not found")

    existing = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == target_user.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="User is already a member")

    role_map = {
        "admin": OrganizationRole.ADMIN,
        "member": OrganizationRole.MEMBER,
        "readonly": OrganizationRole.READ_ONLY,
    }
    role = role_map.get(body.role.lower(), OrganizationRole.MEMBER)

    from datetime import datetime
    new_member = OrganizationMember(
        organization_id=org_id,
        user_id=target_user.id,
        role=role,
        invited_at=datetime.utcnow(),
        joined_at=datetime.utcnow(),
    )
    db.add(new_member)
    await db.commit()
    await db.refresh(new_member)

    return {
        "id": new_member.id,
        "email": target_user.email,
        "role": new_member.role.value,
        "message": "Member added successfully",
    }


@router.delete("/members/{member_id}")
async def remove_member(
    member_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Remove a member from the organization."""
    target_result = await db.execute(
        select(OrganizationMember).where(OrganizationMember.id == member_id)
    )
    target = target_result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    my_membership = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.organization_id == target.organization_id,
            OrganizationMember.role.in_([OrganizationRole.OWNER, OrganizationRole.ADMIN]),
        )
    )
    if not my_membership.scalar_one_or_none():
        org = await db.execute(
            select(Organization).where(
                Organization.id == target.organization_id,
                Organization.owner_id == current_user.id,
            )
        )
        if not org.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="Not authorized to remove members")

    if target.role == OrganizationRole.OWNER:
        raise HTTPException(status_code=400, detail="Cannot remove the organization owner")

    await db.delete(target)
    await db.commit()
    return {"message": "Member removed successfully"}
