"""Authentication endpoints"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import secrets
import hashlib
import json

from app.core.database import get_db
from app.core.security import (
    verify_password,
    create_access_token,
    create_refresh_token,
    get_current_active_user,
    get_optional_current_user,
)
from app.schemas.user import (
    UserCreate,
    UserLogin,
    UserResponse,
    TokenResponse,
)
from app.schemas.api_token import (
    APITokenCreate,
    APITokenResponse,
    APITokenCreated,
)
from app.services.user_service import UserService
from app.models.user import User, APIToken

router = APIRouter()


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    user_create: UserCreate,
    db: AsyncSession = Depends(get_db)
):
    """Register new user"""
    user_service = UserService(db)
    
    # Check if user already exists
    existing_user = await user_service.get_by_email(user_create.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create user
    user = await user_service.create(user_create)
    await db.commit()
    
    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    user_login: UserLogin,
    db: AsyncSession = Depends(get_db)
):
    """Login user and return tokens"""
    user_service = UserService(db)
    
    # Get user by email
    user = await user_service.get_by_email(user_login.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )
    
    # Verify password
    if not verify_password(user_login.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )
    
    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )
    
    # Update last login
    await user_service.update_last_login(user)
    await db.commit()
    
    # Create tokens
    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_active_user)
):
    """Get current user information"""
    return current_user


@router.get("/api-keys", response_model=List[APITokenResponse])
async def get_api_keys(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    # Получить список API ключей пользователя
    
    Возвращает все API токены текущего пользователя (без самих токенов, только метаданные).
    
    **Примечание:** Сам токен показывается только при создании и не сохраняется в открытом виде.
    """
    result = await db.execute(
        select(APIToken)
        .where(APIToken.user_id == current_user.id)
        .order_by(APIToken.created_at.desc())
    )
    tokens = result.scalars().all()
    
    # Format response with key preview
    return [
        APITokenResponse(
            id=token.id,
            user_id=token.user_id,
            name=token.name,
            key_preview=f"fck_{token.token_hash[:8]}",  # Show first 8 chars of hash
            scopes=token.scopes,
            allowed_ips=token.allowed_ips,
            is_active=token.is_active,
            expires_at=token.expires_at,
            last_used_at=token.last_used_at,
            created_at=token.created_at,
        )
        for token in tokens
    ]


@router.post("/api-keys", response_model=APITokenCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    token_create: APITokenCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    # Создать новый API ключ
    
    Создает новый API токен для программного доступа к API.
    
    ## Важно:
    - **Токен показывается только один раз** при создании
    - Сохраните токен в безопасном месте
    - После закрытия окна восстановить токен будет невозможно
    
    ## Использование токена:
    ```bash
    curl -H "Authorization: Bearer YOUR_API_KEY" http://api.example.com/endpoint
    ```
    
    ## Параметры:
    - `name`: Название токена для идентификации
    - `scopes`: Разрешения (опционально)
    - `allowed_ips`: Ограничение по IP (опционально)
    - `expires_at`: Дата истечения (опционально)
    """
    # Generate secure random token
    token = f"fck_{secrets.token_urlsafe(32)}"  # FlareCloud Key
    
    # Hash token for storage
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    # Create token record
    api_token = APIToken(
        user_id=current_user.id,
        name=token_create.name,
        token_hash=token_hash,
        scopes=json.dumps(token_create.scopes) if token_create.scopes else None,
        allowed_ips=json.dumps(token_create.allowed_ips) if token_create.allowed_ips else None,
        expires_at=token_create.expires_at,
        is_active=True,
    )
    
    db.add(api_token)
    await db.commit()
    await db.refresh(api_token)
    
    # Return token (only time it's shown)
    return APITokenCreated(
        id=api_token.id,
        name=api_token.name,
        token=token,  # Full token - shown only once!
        key_preview=f"fck_{token_hash[:8]}",
        created_at=api_token.created_at,
    )


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    key_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    # Удалить API ключ
    
    Удаляет API токен. После удаления токен больше нельзя будет использовать.
    
    **Важно:** Это действие необратимо!
    """
    result = await db.execute(
        select(APIToken).where(
            APIToken.id == key_id,
            APIToken.user_id == current_user.id
        )
    )
    token = result.scalar_one_or_none()
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )
    
    await db.delete(token)
    await db.commit()


@router.patch("/api-keys/{key_id}", response_model=APITokenResponse)
async def update_api_key(
    key_id: int,
    is_active: bool,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    # Активировать/деактивировать API ключ
    
    Позволяет временно отключить токен без удаления.
    """
    result = await db.execute(
        select(APIToken).where(
            APIToken.id == key_id,
            APIToken.user_id == current_user.id
        )
    )
    token = result.scalar_one_or_none()
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )
    
    token.is_active = is_active
    await db.commit()
    await db.refresh(token)
    
    return APITokenResponse(
        id=token.id,
        user_id=token.user_id,
        name=token.name,
        key_preview=f"fck_{token.token_hash[:8]}",
        scopes=token.scopes,
        allowed_ips=token.allowed_ips,
        is_active=token.is_active,
        expires_at=token.expires_at,
        last_used_at=token.last_used_at,
        created_at=token.created_at,
    )


