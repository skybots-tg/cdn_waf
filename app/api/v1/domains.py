"""Domain endpoints"""
from typing import List, Optional, Set, Tuple
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession
import logging

import dns.resolver
import dns.exception

from app.core.database import get_db
from app.core.security import get_current_active_user, get_optional_current_user
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
logger = logging.getLogger(__name__)

PUBLIC_RESOLVERS = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
BASE_RECORD_TYPES = ["A", "AAAA", "MX", "TXT", "CNAME", "NS"]


async def _resolve(
    resolver: dns.resolver.Resolver,
    name: str,
    record_type: str,
):
    """Безопасная обёртка над resolver.resolve в threadpool."""
    try:
        answers = await run_in_threadpool(
            resolver.resolve,
            name,
            record_type,
        )
        return answers
    except (
        dns.resolver.NXDOMAIN,
        dns.resolver.NoAnswer,
        dns.resolver.NoNameservers,
        dns.exception.Timeout,
    ):
        return None
    except Exception as exc:
        logger.warning(
            "Error resolving %s %s: %s",
            name,
            record_type,
            exc,
        )
        return None


@router.get("/scan-dns")
async def scan_dns_records(
    domain: str = Query(..., description="Domain name to scan"),
    nameservers: Optional[List[str]] = Query(
        None,
        description=(
            "Необязательный список NS, к которым ходить напрямую "
            "(например, NS старой DNS-панели)"
        ),
    ),
    current_user: User = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Сканирует публичные DNS-записи домена, а также популярных поддоменов.

    Если передать ?nameservers=ns1.example.com&nameservers=ns2.example.com,
    будет использовать их как источники (для импорта из старой панели).
    """
    records: List[dict] = []
    seen: Set[Tuple[str, str, str, Optional[int]]] = set()

    resolver = dns.resolver.Resolver(configure=True)
    resolver.timeout = 3
    resolver.lifetime = 3

    # Если указаны NS – используем их (это как раз «старая панель»)
    if nameservers:
        resolver.nameservers = nameservers
    else:
        # Пытаемся использовать публичные DNS – чтобы не зависеть от local resolv.conf
        try:
            resolver.nameservers = PUBLIC_RESOLVERS
        except Exception:
            # В худшем случае останемся с системной конфигурацией
            pass

    def add_record(data: dict):
        """Добавляет запись, избегая дублей."""
        key = (
            data["type"],
            data["name"],
            data.get("content", ""),
            data.get("priority"),
        )
        if key in seen:
            return
        seen.add(key)
        records.append(data)

    # ---------- корневые записи домена ----------
    for record_type in BASE_RECORD_TYPES:
        answers = await _resolve(resolver, domain, record_type)
        if not answers:
            continue

        ttl = answers.rrset.ttl if answers.rrset is not None else None

        for rdata in answers:
            record = {
                "type": record_type,
                "name": "@",
                "ttl": ttl,
                "proxied": record_type in ["A", "AAAA", "CNAME"],
            }

            if record_type in ("A", "AAAA"):
                record["content"] = str(rdata)
            elif record_type == "CNAME":
                record["content"] = str(getattr(rdata, "target", rdata)).rstrip(".")
            elif record_type == "MX":
                record["content"] = str(rdata.exchange).rstrip(".")
                record["priority"] = rdata.preference
            elif record_type == "TXT":
                # dnspython 2.x: rdata.strings может отсутствовать, но у тебя уже был такой код — оставляю
                txt_parts = getattr(rdata, "strings", None)
                if txt_parts:
                    record["content"] = " ".join(
                        s.decode() if isinstance(s, bytes) else s
                        for s in txt_parts
                    )
                else:
                    record["content"] = rdata.to_text().strip('"')
            elif record_type == "NS":
                record["content"] = str(rdata).rstrip(".")
                record["proxied"] = False

            add_record(record)

    # ---------- популярные поддомены ----------
    common_subdomains = [
        "www",
        "mail",
        "remote",
        "blog",
        "webmail",
        "server",
        "ns1",
        "ns2",
        "smtp",
        "secure",
        "vpn",
        "m",
        "shop",
        "ftp",
        "api",
        "portal",
        "admin",
        "autodiscover",
        "imap",
        "pop",
        "dev",
        "test",
        "staging",
        "app",
        "cdn",
        "dashboard",
        "auth",
        "payment",
        "docs",
        "files",
        "static",
    ]

    for subdomain in common_subdomains:
        fqdn = f"{subdomain}.{domain}"

        for sub_type in ["A", "AAAA", "CNAME"]:
            answers = await _resolve(resolver, fqdn, sub_type)
            if not answers:
                continue

            ttl = answers.rrset.ttl if answers.rrset is not None else None

            for rdata in answers:
                record = {
                    "type": sub_type,
                    "name": subdomain,
                    "ttl": ttl,
                    "proxied": sub_type in ["A", "AAAA", "CNAME"],
                }

                if sub_type in ("A", "AAAA"):
                    record["content"] = str(rdata)
                elif sub_type == "CNAME":
                    record["content"] = str(getattr(rdata, "target", rdata)).rstrip(".")

                add_record(record)

    return records


@router.get("/", response_model=List[DomainResponse])
async def list_domains(
    current_user: User = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all domains for current user's organization"""
    if not current_user:
        # For development, allow unauthenticated access
        pass

    # TODO: Get organization_id from current user's context
    organization_id = 1

    domain_service = DomainService(db)
    domains = await domain_service.list_by_organization(organization_id)
    return domains


@router.post("/", response_model=DomainResponse, status_code=status.HTTP_201_CREATED)
async def create_domain(
    domain_create: DomainCreate,
    current_user: User = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create new domain"""
    if not current_user:
        # For development, allow domain creation without auth
        # TODO: Require authentication in production
        pass

    # TODO: Get organization_id from current user's context
    organization_id = 1

    domain_service = DomainService(db)

    existing_domain = await domain_service.get_by_name(domain_create.name)
    if existing_domain:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Domain already exists",
        )

    domain = await domain_service.create(organization_id, domain_create)
    await db.commit()

    return domain


@router.get("/{domain_id}", response_model=DomainResponse)
async def get_domain(
    domain_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get domain by ID"""
    domain_service = DomainService(db)
    domain = await domain_service.get_by_id(domain_id)

    if not domain:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domain not found",
        )

    # TODO: Check if user has access to this domain

    return domain


@router.patch("/{domain_id}", response_model=DomainResponse)
async def update_domain(
    domain_id: int,
    domain_update: DomainUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update domain"""
    domain_service = DomainService(db)
    domain = await domain_service.get_by_id(domain_id)

    if not domain:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domain not found",
        )

    # TODO: Check if user has access to this domain

    domain = await domain_service.update(domain, domain_update)
    await db.commit()

    return domain


@router.post("/{domain_id}/verify-ns")
async def verify_ns(
    domain_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify NS records for domain"""
    domain_service = DomainService(db)
    domain = await domain_service.get_by_id(domain_id)

    if not domain:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domain not found",
        )

    # TODO: Check if user has access to this domain

    verified = await domain_service.verify_ns(domain)
    await db.commit()

    return {"verified": verified, "domain_id": domain_id}
