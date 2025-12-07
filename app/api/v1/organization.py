"""Organization management endpoints"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import get_optional_current_user
from app.models.user import User
from app.models.organization import Organization, OrganizationMember

router = APIRouter()


@router.get("/members")
async def get_organization_members(
    current_user: User = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all members of user's organization
    
    Note: Returns empty list if user not authenticated or organization not configured.
    """
    if not current_user:
        return []
    
    # Get user's organization membership
    result = await db.execute(
        select(OrganizationMember)
        .where(OrganizationMember.user_id == current_user.id)
    )
    membership = result.scalar_one_or_none()
    
    if not membership:
        return []
    
    # Get all members of the organization
    result = await db.execute(
        select(OrganizationMember, User)
        .join(User, OrganizationMember.user_id == User.id)
        .where(OrganizationMember.organization_id == membership.organization_id)
    )
    members_data = result.all()
    
    return [
        {
            "id": member.id,
            "email": user.email,
            "role": member.role.value,
            "created_at": member.created_at.isoformat() if member.created_at else None
        }
        for member, user in members_data
    ]


@router.post("/members/invite")
async def invite_member(
    email: str,
    role: str,
    current_user: User = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Invite new member to organization
    
    Note: Not yet fully implemented.
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    
    # TODO: Implement member invitation
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Member invitation not yet implemented"
    )


@router.delete("/members/{member_id}")
async def remove_member(
    member_id: int,
    current_user: User = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Remove member from organization
    
    Note: Not yet fully implemented.
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    
    # TODO: Implement member removal
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Member removal not yet implemented"
    )
