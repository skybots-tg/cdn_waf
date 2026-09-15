"""Domain endpoints"""
import asyncio
import re
from typing import List, Optional, Set, Tuple
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging


import dns.resolver
import dns.exception

from app.core.database import get_db
from app.core.security import get_current_active_user, get_allowed_domain_ids
from app.api.v1.dependencies import (
    get_domain_for_user,
    get_user_org_ids,
    get_or_create_primary_org,
)
from app.schemas.domain import (
    DomainCreate,
    DomainUpdate,
    DomainResponse,
)
from app.services.domain_service import DomainService
from app.models.user import User
from app.models.domain import Domain, DomainStatus
from app.models.dns import DNSRecord
from app.models.certificate import Certificate, CertificateStatus
from app.tasks.dns_tasks import sync_dns_nodes

router = APIRouter()
logger = logging.getLogger(__name__)

PUBLIC_RESOLVERS = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
BASE_RECORD_TYPES = ["A", "AAAA", "MX", "TXT", "CNAME", "NS"]

# A conservative hostname matcher (labels of a-z0-9-, dots between them).
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$"
)


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


@router.get("/scan-dns", tags=["dns"])
async def scan_dns_records(
    domain: str = Query(..., description="Domain name to scan"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    # Сканировать существующие DNS записи домена

    Сканирует DNS записи через фиксированный список публичных резолверов.
    """
    # Reject anything that isn't a bare hostname so this can't be turned into an
    # arbitrary-target DNS query engine (the caller no longer picks nameservers).
    if not _HOSTNAME_RE.match(domain or ""):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid domain name",
        )

    records: List[dict] = []
    seen: Set[Tuple[str, str, str, Optional[int]]] = set()

    resolver = dns.resolver.Resolver(configure=True)
    resolver.timeout = 3
    resolver.lifetime = 3

    # Always use our fixed public resolvers; a caller-supplied nameserver list
    # would let this endpoint reflect DNS traffic at (or probe) arbitrary hosts.
    try:
        resolver.nameservers = PUBLIC_RESOLVERS
    except Exception as exc:
        logger.warning("Failed to set public resolvers: %s", exc)

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

    # --- Collect all queries to run in parallel ---

    common_subdomains = [
        "www", "mail", "remote", "blog", "webmail", "server",
        "ns1", "ns2", "smtp", "secure", "vpn", "m", "shop",
        "ftp", "api", "portal", "admin", "autodiscover", "imap",
        "pop", "dev", "test", "staging", "app", "cdn", "dashboard",
        "auth", "payment", "docs", "files", "static",
    ]
    txt_subdomains = ["_dmarc", "_domainkey", "_spf", "_mta-sts", "_smtp._tls"]

    tasks: list = []
    task_meta: list = []  # (name_label, record_type, fqdn)

    for record_type in BASE_RECORD_TYPES:
        tasks.append(_resolve(resolver, domain, record_type))
        task_meta.append(("@", record_type, domain))

    for subdomain in common_subdomains:
        fqdn = f"{subdomain}.{domain}"
        for sub_type in ["A", "AAAA", "CNAME"]:
            tasks.append(_resolve(resolver, fqdn, sub_type))
            task_meta.append((subdomain, sub_type, fqdn))

    for subdomain in txt_subdomains:
        fqdn = f"{subdomain}.{domain}"
        tasks.append(_resolve(resolver, fqdn, "TXT"))
        task_meta.append((subdomain, "TXT", fqdn))

    # Run all DNS queries concurrently
    results = await asyncio.gather(*tasks)

    # --- Process results ---

    for (name_label, record_type, _fqdn), answers in zip(task_meta, results):
        if not answers:
            continue

        ttl = answers.rrset.ttl if answers.rrset is not None else None

        for rdata in answers:
            record = {
                "type": record_type,
                "name": name_label,
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
                txt_parts = getattr(rdata, "strings", None)
                if txt_parts:
                    record["content"] = "".join(
                        s.decode() if isinstance(s, bytes) else s
                        for s in txt_parts
                    )
                else:
                    record["content"] = rdata.to_text().strip('"')
            elif record_type == "NS":
                record["content"] = str(rdata).rstrip(".")
                record["proxied"] = False

            add_record(record)

    return records


@router.get("/", response_model=List[DomainResponse])
async def list_domains(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List domains the caller may see (their organizations; all, for superusers)."""
    domain_service = DomainService(db)

    if current_user.is_superuser:
        domains = await domain_service.list_all()
    else:
        org_ids = await get_user_org_ids(current_user, db)
        domains = []
        for org_id in org_ids:
            domains.extend(await domain_service.list_by_organization(org_id))

    # Filter by API-token domain scoping if applicable.
    allowed_domain_ids = get_allowed_domain_ids(current_user)
    if allowed_domain_ids is not None:
        domains = [d for d in domains if d.id in allowed_domain_ids]

    return domains


@router.post("/", response_model=DomainResponse, status_code=status.HTTP_201_CREATED)
async def create_domain(
    domain_create: DomainCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new domain inside the caller's own organization."""
    organization_id = await get_or_create_primary_org(current_user, db)

    domain_service = DomainService(db)

    existing_domain = await domain_service.get_by_name(domain_create.name)
    if existing_domain:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Domain already exists",
        )

    domain = await domain_service.create(organization_id, domain_create)
    await db.commit()

    sync_dns_nodes.delay()
    return domain


@router.get("/{domain_id}", response_model=DomainResponse)
async def get_domain(
    domain: Domain = Depends(get_domain_for_user),
):
    """Get domain by ID (ownership enforced by the dependency)."""
    return domain


@router.get("/{domain_id}/info", tags=["domains"])
async def get_domain_info(
    domain: Domain = Depends(get_domain_for_user),
    db: AsyncSession = Depends(get_db),
):
    """
    # Получить полную информацию о домене

    Возвращает домен, DNS записи, сертификаты и статистику.
    """
    domain_id = domain.id

    # Get DNS records
    dns_result = await db.execute(
        select(DNSRecord)
        .where(DNSRecord.domain_id == domain_id)
        .order_by(DNSRecord.type, DNSRecord.name)
    )
    dns_records = dns_result.scalars().all()
    
    # Get certificates
    certs_result = await db.execute(
        select(Certificate)
        .where(Certificate.domain_id == domain_id)
        .order_by(Certificate.created_at.desc())
    )
    certificates = certs_result.scalars().all()
    
    # Stats
    active_certs = sum(1 for c in certificates if c.status == CertificateStatus.ISSUED)
    proxied_records = sum(1 for r in dns_records if r.proxied)
    
    return {
        "domain": {
            "id": domain.id,
            "organization_id": domain.organization_id,
            "name": domain.name,
            "status": domain.status,
            "ns_verified": domain.ns_verified,
            "ns_verified_at": domain.ns_verified_at.isoformat() if domain.ns_verified_at else None,
            "created_at": domain.created_at.isoformat() if domain.created_at else None,
            "updated_at": domain.updated_at.isoformat() if domain.updated_at else None,
        },
        "dns_records": [
            {
                "id": r.id,
                "type": r.type,
                "name": r.name,
                "content": r.content,
                "ttl": r.ttl,
                "priority": r.priority,
                "proxied": r.proxied,
                "comment": r.comment,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in dns_records
        ],
        "certificates": [
            {
                "id": c.id,
                "common_name": c.common_name,
                "status": c.status.value,
                "type": c.type.value if hasattr(c.type, 'value') else c.type,
                "issuer": c.issuer,
                "not_before": c.not_before.isoformat() if c.not_before else None,
                "not_after": c.not_after.isoformat() if c.not_after else None,
                "auto_renew": c.auto_renew,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in certificates
        ],
        "stats": {
            "total_dns_records": len(dns_records),
            "active_certificates": active_certs,
            "proxied_records": proxied_records,
            "dns_record_types": {
                rt: sum(1 for r in dns_records if r.type == rt)
                for rt in set(r.type for r in dns_records)
            },
        }
    }


@router.patch("/{domain_id}", response_model=DomainResponse)
async def update_domain(
    domain_update: DomainUpdate,
    domain: Domain = Depends(get_domain_for_user),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update domain (ownership enforced by the dependency)."""
    # Going "active" is what publishes a domain to the edge fleet; don't let a
    # tenant flip that on for a domain whose NS ownership hasn't been verified.
    new_status = getattr(domain_update, "status", None)
    if new_status is not None and str(getattr(new_status, "value", new_status)) == DomainStatus.ACTIVE.value:
        if not domain.ns_verified and not current_user.is_superuser:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Domain NS must be verified before it can be activated",
            )

    domain_service = DomainService(db)
    domain = await domain_service.update(domain, domain_update)
    await db.commit()

    sync_dns_nodes.delay()
    return domain


@router.post("/{domain_id}/verify-ns")
async def verify_ns(
    domain: Domain = Depends(get_domain_for_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify NS records for domain (ownership enforced by the dependency)."""
    domain_service = DomainService(db)
    verified = await domain_service.verify_ns(domain)
    await db.commit()

    return {"verified": verified, "domain_id": domain.id}


@router.delete("/{domain_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_domain(
    domain: Domain = Depends(get_domain_for_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete domain (ownership enforced by the dependency)."""
    domain_service = DomainService(db)
    await domain_service.delete(domain)
    await db.commit()

    sync_dns_nodes.delay()
