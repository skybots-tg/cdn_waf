"""Domain endpoints"""
from typing import List, Optional, Set, Tuple
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging

from app.core.config import settings

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
from app.models.dns import DNSRecord
from app.models.certificate import Certificate, CertificateStatus
from app.tasks.dns_tasks import sync_dns_nodes

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

    # Trigger sync to DNS nodes
    sync_dns_nodes.delay()

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

    # Trigger sync to DNS nodes
    sync_dns_nodes.delay()

    return domain


from app.services.ssl_service import SSLService
from pydantic import BaseModel

class ACMERequest(BaseModel):
    wildcard: bool = False

@router.post("/{domain_id}/ssl/certificates/acme")
async def request_acme_certificate(
    domain_id: int,
    request: ACMERequest,
    current_user: User = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Request Let's Encrypt certificate for domain"""
    # TODO: Auth check
    
    try:
        certificate = await SSLService.request_acme_certificate(
            db, domain_id, request.wildcard
        )
        return {"status": "pending", "certificate_id": certificate.id}
    except Exception as e:
        logger.error(f"Failed to request ACME certificate: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
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


@router.post("/{domain_id}/issue-certificate/{subdomain}")
async def issue_subdomain_certificate(
    domain_id: int,
    subdomain: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Выпустить Let's Encrypt сертификат для домена или поддомена
    
    Args:
        domain_id: ID домена
        subdomain: @ для основного домена, или имя A-записи для поддомена
    """
    # Получаем домен
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    
    # Проверяем права доступа
    if domain.organization_id != current_user.organization_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Формируем полное имя домена
    if subdomain == "@":
        fqdn = domain.name
    else:
        # Проверяем существует ли такая A-запись
        dns_result = await db.execute(
            select(DNSRecord).where(
                DNSRecord.domain_id == domain_id,
                DNSRecord.name == subdomain,
                DNSRecord.type == "A"
            )
        )
        dns_record = dns_result.scalar_one_or_none()
        if not dns_record:
            raise HTTPException(status_code=404, detail=f"DNS A record '{subdomain}' not found")
        
        fqdn = f"{subdomain}.{domain.name}"
    
    # Проверяем нет ли уже активного сертификата
    existing_cert = await db.execute(
        select(Certificate).where(
            Certificate.domain_id == domain_id,
            Certificate.common_name == fqdn,
            Certificate.status == CertificateStatus.ISSUED
        )
    )
    if existing_cert.scalar_one_or_none():
        raise HTTPException(
            status_code=400, 
            detail=f"Certificate for {fqdn} already exists. Delete it first if you want to reissue."
        )
    
    # Создаем PENDING сертификат
    cert = Certificate(
        domain_id=domain_id,
        type="acme",
        status=CertificateStatus.PENDING,
        common_name=fqdn,
        issuer=None,
        subject=None,
        auto_renew=True
    )
    db.add(cert)
    await db.commit()
    await db.refresh(cert)
    
    # Запускаем задачу выпуска в фоне через Celery
    from app.tasks.certificate_tasks import issue_certificate
    issue_certificate.delay(domain_id)
    
    return JSONResponse({
        "status": "pending",
        "message": f"Certificate issuance started for {fqdn}",
        "certificate_id": cert.id,
        "fqdn": fqdn
    })


@router.get("/{domain_id}/certificates")
async def list_domain_certificates(
    domain_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Получить список всех сертификатов для домена"""
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    
    if domain.organization_id != current_user.organization_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Получаем все сертификаты
    certs_result = await db.execute(
        select(Certificate).where(Certificate.domain_id == domain_id)
        .order_by(Certificate.created_at.desc())
    )
    certificates = certs_result.scalars().all()
    
    return [
        {
            "id": cert.id,
            "common_name": cert.common_name,
            "status": cert.status.value,
            "issuer": cert.issuer,
            "not_before": cert.not_before.isoformat() if cert.not_before else None,
            "not_after": cert.not_after.isoformat() if cert.not_after else None,
            "created_at": cert.created_at.isoformat()
        }
        for cert in certificates
    ]


@router.delete("/{domain_id}/certificates/{cert_id}")
async def delete_certificate(
    domain_id: int,
    cert_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Удалить сертификат"""
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    
    if domain.organization_id != current_user.organization_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    cert_result = await db.execute(
        select(Certificate).where(
            Certificate.id == cert_id,
            Certificate.domain_id == domain_id
        )
    )
    cert = cert_result.scalar_one_or_none()
    
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    
    await db.delete(cert)
    await db.commit()
    
    return {"status": "deleted", "certificate_id": cert_id}


@router.get("/{domain_id}/certificates/available")
async def get_available_certificates(
    domain_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_optional_current_user)
):
    """
    Получить список доменов/поддоменов доступных к выдаче сертификата
    (DNS записи с proxied=True, у которых нет активного сертификата)
    """
    # Получаем домен
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    
    # Получаем все проксируемые DNS записи типа A
    dns_result = await db.execute(
        select(DNSRecord).where(
            DNSRecord.domain_id == domain_id,
            DNSRecord.type == "A",
            DNSRecord.proxied == True
        )
    )
    dns_records = dns_result.scalars().all()
    
    # Получаем все активные сертификаты
    certs_result = await db.execute(
        select(Certificate).where(
            Certificate.domain_id == domain_id,
            Certificate.status == CertificateStatus.ISSUED
        )
    )
    active_certs = certs_result.scalars().all()
    
    # Создаем множество доменов, для которых уже есть сертификаты
    covered_domains = set()
    for cert in active_certs:
        if cert.common_name:
            covered_domains.add(cert.common_name)
    
    # Формируем список доступных к выдаче
    available = []
    
    # Проверяем основной домен
    if domain.name not in covered_domains:
        available.append({
            "subdomain": "@",
            "fqdn": domain.name,
            "dns_record_id": None
        })
    
    # Проверяем поддомены
    for record in dns_records:
        if record.name == "@":
            continue  # Уже проверили выше
        
        fqdn = f"{record.name}.{domain.name}"
        if fqdn not in covered_domains:
            available.append({
                "subdomain": record.name,
                "fqdn": fqdn,
                "dns_record_id": record.id
            })
    
    return available


@router.post("/{domain_id}/certificates/issue")
async def issue_certificate_for_subdomain(
    domain_id: int,
    subdomain: str,
    email: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_optional_current_user)
):
    """
    Выпустить Let's Encrypt сертификат для домена или поддомена
    
    Args:
        domain_id: ID домена
        subdomain: @ для основного домена, или имя поддомена
        email: Email для уведомлений ACME (опционально, по умолчанию из config)
    """
    from app.models.certificate_log import CertificateLog, CertificateLogLevel
    
    # Получаем домен
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    
    # Формируем полное имя домена
    if subdomain == "@":
        fqdn = domain.name
    else:
        # Проверяем существует ли такая A-запись
        dns_result = await db.execute(
            select(DNSRecord).where(
                DNSRecord.domain_id == domain_id,
                DNSRecord.name == subdomain,
                DNSRecord.type == "A",
                DNSRecord.proxied == True
            )
        )
        dns_record = dns_result.scalar_one_or_none()
        if not dns_record:
            raise HTTPException(
                status_code=404, 
                detail=f"Proxied DNS A record '{subdomain}' not found"
            )
        
        fqdn = f"{subdomain}.{domain.name}"
    
    # Проверяем нет ли уже активного или pending сертификата
    existing_cert = await db.execute(
        select(Certificate).where(
            Certificate.domain_id == domain_id,
            Certificate.common_name == fqdn,
            Certificate.status.in_([CertificateStatus.ISSUED, CertificateStatus.PENDING])
        )
    )
    if existing_cert.scalar_one_or_none():
        raise HTTPException(
            status_code=400, 
            detail=f"Certificate for {fqdn} already exists or is being issued"
        )
    
    # Создаем PENDING сертификат
    from app.models.certificate import CertificateType
    cert = Certificate(
        domain_id=domain_id,
        type=CertificateType.ACME,
        status=CertificateStatus.PENDING,
        common_name=fqdn,
        issuer=None,
        subject=None,
        auto_renew=True,
        acme_challenge_type="http-01"
    )
    db.add(cert)
    await db.commit()
    await db.refresh(cert)
    
    # Добавляем начальный лог
    log_entry = CertificateLog(
        certificate_id=cert.id,
        level=CertificateLogLevel.INFO,
        message=f"Certificate issuance started for {fqdn}",
        details=f'{{"subdomain": "{subdomain}", "email": "{email or settings.ACME_EMAIL}"}}'
    )
    db.add(log_entry)
    await db.commit()
    
    # Запускаем задачу выпуска в фоне через Celery
    from app.tasks.certificate_tasks import issue_single_certificate
    issue_single_certificate.delay(cert.id, email)
    
    return JSONResponse({
        "status": "pending",
        "message": f"Certificate issuance started for {fqdn}",
        "certificate_id": cert.id,
        "fqdn": fqdn
    })


@router.get("/{domain_id}/certificates/{cert_id}/logs")
async def get_certificate_logs(
    domain_id: int,
    cert_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_optional_current_user)
):
    """Получить логи выдачи сертификата"""
    from app.models.certificate_log import CertificateLog
    
    # Проверяем что сертификат принадлежит домену
    cert_result = await db.execute(
        select(Certificate).where(
            Certificate.id == cert_id,
            Certificate.domain_id == domain_id
        )
    )
    cert = cert_result.scalar_one_or_none()
    
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    
    # Получаем логи
    logs_result = await db.execute(
        select(CertificateLog)
        .where(CertificateLog.certificate_id == cert_id)
        .order_by(CertificateLog.created_at.asc())
    )
    logs = logs_result.scalars().all()
    
    return [
        {
            "id": log.id,
            "level": log.level.value,
            "message": log.message,
            "details": log.details,
            "created_at": log.created_at.isoformat()
        }
        for log in logs
    ]