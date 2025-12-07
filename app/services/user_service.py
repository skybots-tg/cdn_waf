"""User service"""
from typing import Optional
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, APIToken
from app.schemas.user import UserCreate, UserUpdate
from app.core.security import get_password_hash


class UserService:
    """User service for database operations"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_by_id(self, user_id: int) -> Optional[User]:
        """Get user by ID"""
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email"""
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()
    
    async def create(self, user_create: UserCreate) -> User:
        """Create new user"""
        user = User(
            email=user_create.email,
            password_hash=get_password_hash(user_create.password),
            full_name=user_create.full_name,
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user
    
    async def update(self, user: User, user_update: UserUpdate) -> User:
        """Update user"""
        if user_update.full_name is not None:
            user.full_name = user_update.full_name
        if user_update.password is not None:
            user.password_hash = get_password_hash(user_update.password)
        
        user.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(user)
        return user
    
    async def update_last_login(self, user: User):
        """Update last login timestamp"""
        user.last_login = datetime.utcnow()
        await self.db.flush()


