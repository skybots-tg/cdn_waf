"""Authentication endpoints"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
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
    APITokenUpdate,
    APITokenResponse,
    APITokenCreated,
    DomainBrief,
)
from app.services.user_service import UserService
from app.models.user import User, APIToken
from app.models.domain import Domain
from app.models.organization import Organization, OrganizationMember

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


@router.get("/my-domains", response_model=List[DomainBrief])
async def get_user_domains(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    # Получить список доменов пользователя
    
    Возвращает все домены, доступные текущему пользователю через его организации.
    Используется для выбора доменов при создании API ключа.
    """
    # Get user's organizations (owned + member)
    org_ids_result = await db.execute(
        select(Organization.id).where(Organization.owner_id == current_user.id)
    )
    owned_org_ids = [row[0] for row in org_ids_result.fetchall()]
    
    member_org_ids_result = await db.execute(
        select(OrganizationMember.organization_id)
        .where(OrganizationMember.user_id == current_user.id)
    )
    member_org_ids = [row[0] for row in member_org_ids_result.fetchall()]
    
    user_org_ids = set(owned_org_ids + member_org_ids)
    
    if not user_org_ids:
        return []
    
    # Get all domains from user's organizations
    domains_result = await db.execute(
        select(Domain)
        .where(Domain.organization_id.in_(user_org_ids))
        .order_by(Domain.name)
    )
    domains = domains_result.scalars().all()
    
    return [DomainBrief(id=d.id, name=d.name) for d in domains]


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
        .options(selectinload(APIToken.allowed_domains))
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
            allowed_domains=[DomainBrief(id=d.id, name=d.name) for d in token.allowed_domains],
            all_domains_access=len(token.allowed_domains) == 0,
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
    - `domain_ids`: Список ID доменов (опционально, пусто = доступ ко всем доменам)
    """
    # Generate secure random token
    token = f"fck_{secrets.token_urlsafe(32)}"  # FlareCloud Key
    
    # Hash token for storage
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    # Validate domain_ids if provided - ensure user has access to these domains
    allowed_domains = []
    if token_create.domain_ids:
        # Get user's organizations
        org_ids_result = await db.execute(
            select(Organization.id).where(Organization.owner_id == current_user.id)
        )
        owned_org_ids = [row[0] for row in org_ids_result.fetchall()]
        
        member_org_ids_result = await db.execute(
            select(OrganizationMember.organization_id)
            .where(OrganizationMember.user_id == current_user.id)
        )
        member_org_ids = [row[0] for row in member_org_ids_result.fetchall()]
        
        user_org_ids = set(owned_org_ids + member_org_ids)
        
        # Get domains that belong to user's organizations
        domains_result = await db.execute(
            select(Domain)
            .where(
                Domain.id.in_(token_create.domain_ids),
                Domain.organization_id.in_(user_org_ids)
            )
        )
        allowed_domains = domains_result.scalars().all()
        
        # Check if all requested domains were found and belong to user
        found_domain_ids = {d.id for d in allowed_domains}
        missing_ids = set(token_create.domain_ids) - found_domain_ids
        if missing_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Domains not found or access denied: {missing_ids}"
            )
    
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
    
    # Add allowed domains
    if allowed_domains:
        api_token.allowed_domains = allowed_domains
    
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
        allowed_domains=[DomainBrief(id=d.id, name=d.name) for d in allowed_domains],
        all_domains_access=len(allowed_domains) == 0,
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


@router.put("/api-keys/{key_id}", response_model=APITokenResponse)
async def update_api_key(
    key_id: int,
    token_update: APITokenUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    # Обновить API ключ
    
    Позволяет обновить название, статус и доступ к доменам для API ключа.
    
    ## Параметры:
    - `name`: Новое название токена (опционально)
    - `is_active`: Активировать/деактивировать токен (опционально)
    - `domain_ids`: Список ID доменов для ограничения доступа (опционально)
    - `all_domains_access`: Если true, даёт доступ ко всем доменам (опционально)
    """
    result = await db.execute(
        select(APIToken)
        .options(selectinload(APIToken.allowed_domains))
        .where(
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
    
    # Update name if provided
    if token_update.name is not None:
        token.name = token_update.name
    
    # Update is_active if provided
    if token_update.is_active is not None:
        token.is_active = token_update.is_active
    
    # Handle domain access updates
    if token_update.all_domains_access is True:
        # Clear all domain restrictions - give access to all domains
        token.allowed_domains = []
    elif token_update.domain_ids is not None:
        # Validate and set specific domains
        if len(token_update.domain_ids) == 0:
            # Empty list = all domains access
            token.allowed_domains = []
        else:
            # Get user's organizations
            org_ids_result = await db.execute(
                select(Organization.id).where(Organization.owner_id == current_user.id)
            )
            owned_org_ids = [row[0] for row in org_ids_result.fetchall()]
            
            member_org_ids_result = await db.execute(
                select(OrganizationMember.organization_id)
                .where(OrganizationMember.user_id == current_user.id)
            )
            member_org_ids = [row[0] for row in member_org_ids_result.fetchall()]
            
            user_org_ids = set(owned_org_ids + member_org_ids)
            
            # Get domains that belong to user's organizations
            domains_result = await db.execute(
                select(Domain)
                .where(
                    Domain.id.in_(token_update.domain_ids),
                    Domain.organization_id.in_(user_org_ids)
                )
            )
            allowed_domains = domains_result.scalars().all()
            
            # Check if all requested domains were found and belong to user
            found_domain_ids = {d.id for d in allowed_domains}
            missing_ids = set(token_update.domain_ids) - found_domain_ids
            if missing_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Domains not found or access denied: {missing_ids}"
                )
            
            token.allowed_domains = list(allowed_domains)
    
    await db.commit()
    await db.refresh(token)
    
    # Reload allowed_domains relationship
    result = await db.execute(
        select(APIToken)
        .options(selectinload(APIToken.allowed_domains))
        .where(APIToken.id == token.id)
    )
    token = result.scalar_one()
    
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
        allowed_domains=[DomainBrief(id=d.id, name=d.name) for d in token.allowed_domains],
        all_domains_access=len(token.allowed_domains) == 0,
    )


