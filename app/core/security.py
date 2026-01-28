"""Security utilities for authentication and authorization"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from passlib.context import CryptContext
from jose import JWTError, jwt
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import hashlib
import json

from app.core.config import settings
from app.core.database import get_db

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTP Bearer token security - auto_error=False allows optional auth
security = HTTPBearer(auto_error=False)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Generate password hash"""
    return pwd_context.hash(password)


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: Dict[str, Any]) -> str:
    """Create JWT refresh token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> Dict[str, Any]:
    """Decode and verify JWT token"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Could not validate credentials: {str(e)}")


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    db: AsyncSession = Depends(get_db)
):
    """
    Get current authenticated user from JWT token or API key
    
    Supports two authentication methods:
    1. JWT tokens (standard user login)
    2. API keys (for programmatic access, starts with 'fck_')
    
    In DEBUG mode, falls back to admin user if no credentials provided.
    """
    # Import here to avoid circular dependency
    from app.services.user_service import UserService
    
    if not credentials:
        # In DEBUG mode, allow access as default admin if no token provided
        if settings.DEBUG:
            user_service = UserService(db)
            user = await user_service.get_by_id(1)
            if user:
                return user
        
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    
    # Check if this is an API key (starts with 'fck_')
    if token.startswith('fck_'):
        return await authenticate_api_key(token, db)
    
    # Otherwise treat as JWT token
    payload = decode_token(token)
    
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")
    
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Could not validate credentials")
        
    if user_id is None:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    
    user_service = UserService(db)
    user = await user_service.get_by_id(user_id)
    
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user")
    
    return user


async def authenticate_api_key(token: str, db: AsyncSession):
    """Authenticate user using API key"""
    from app.models.user import APIToken, User
    from sqlalchemy.orm import selectinload
    
    # Hash the provided token
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    # Find token in database with allowed domains
    result = await db.execute(
        select(APIToken)
        .options(selectinload(APIToken.allowed_domains))
        .where(APIToken.token_hash == token_hash)
    )
    api_token = result.scalar_one_or_none()
    
    if not api_token:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    # Check if token is active
    if not api_token.is_active:
        raise HTTPException(status_code=401, detail="API key is inactive")
    
    # Check expiration
    if api_token.expires_at and api_token.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="API key has expired")
    
    # Update last used timestamp
    api_token.last_used_at = datetime.utcnow()
    await db.commit()
    
    # Get user
    result = await db.execute(
        select(User).where(User.id == api_token.user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is inactive")
    
    # Store allowed domain IDs on user object for later access checks
    # None/empty means all domains allowed
    user._api_token_allowed_domain_ids = (
        {d.id for d in api_token.allowed_domains} 
        if api_token.allowed_domains else None
    )
    
    return user


def check_domain_access(user, domain_id: int) -> bool:
    """
    Check if user (via API token) has access to a specific domain.
    
    Returns True if:
    - User is authenticated via JWT (not API token) - full access
    - API token has no domain restrictions (all domains allowed)
    - Domain ID is in the token's allowed domains list
    
    Returns False if:
    - API token has domain restrictions and domain_id is not in the list
    """
    # If no _api_token_allowed_domain_ids attribute, user is authenticated via JWT
    allowed_domain_ids = getattr(user, '_api_token_allowed_domain_ids', None)
    
    if allowed_domain_ids is None:
        # No restrictions - either JWT auth or API token with all domains access
        return True
    
    # Check if domain is in allowed list
    return domain_id in allowed_domain_ids


def require_domain_access(user, domain_id: int):
    """
    Require access to a specific domain, raise HTTPException if not allowed.
    """
    if not check_domain_access(user, domain_id):
        raise HTTPException(
            status_code=403,
            detail="API key does not have access to this domain"
        )


async def get_current_active_user(current_user = Depends(get_current_user)):
    """Get current active user"""
    return current_user


async def get_current_superuser(current_user = Depends(get_current_user)):
    """Get current superuser"""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough privileges")
    return current_user


async def get_optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    db: AsyncSession = Depends(get_db)
):
    """Get current user if authenticated, None otherwise (for optional auth endpoints)
    
    This function is used for endpoints that work both with and without authentication.
    In DEBUG mode, returns admin user for convenience.
    In production, returns None if no valid credentials provided.
    """
    from app.services.user_service import UserService
    
    if not credentials:
        # In DEBUG mode, return admin user for convenience
        if settings.DEBUG:
            user_service = UserService(db)
            user = await user_service.get_by_id(1)
            return user
        return None
    
    try:
        token = credentials.credentials
        
        # Check if this is an API key
        if token.startswith('fck_'):
            return await authenticate_api_key(token, db)
        
        # JWT token
        payload = decode_token(token)
        
        if payload.get("type") != "access":
            return None
        
        user_id = int(payload.get("sub"))
        user_service = UserService(db)
        user = await user_service.get_by_id(user_id)
        
        if user and user.is_active:
            return user
        return None
    except Exception:
        return None
