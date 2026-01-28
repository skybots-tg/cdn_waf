"""Certificate management API endpoints"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.config import settings
from app.core.security import get_optional_current_user
from app.models.user import User
from app.models.domain import Domain
from app.models.dns import DNSRecord
from app.models.certificate import Certificate, CertificateStatus, CertificateType
from app.models.certificate_log import CertificateLog, CertificateLogLevel

router = APIRouter()


@router.get("/{domain_id}/certificates")
async def list_domain_certificates(
    domain_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_optional_current_user)
):
    """
    # Получить список всех сертификатов домена
    
    Возвращает все SSL/TLS сертификаты (активные, pending, failed) для указанного домена.
    
    ## Статусы сертификатов:
    - `pending` - в процессе выпуска
    - `issued` - активный сертификат
    - `expired` - истек срок действия
    - `revoked` - отозван
    - `failed` - ошибка при выпуске
    """
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    
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


@router.get("/{domain_id}/certificates/available")
async def get_available_certificates(
    domain_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_optional_current_user)
):
    """
    # Получить список поддоменов доступных для выпуска сертификата
    
    Возвращает все DNS A-записи домена, для которых еще не выпущен SSL сертификат.
    """
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    
    # Get all A records
    dns_result = await db.execute(
        select(DNSRecord).where(
            DNSRecord.domain_id == domain_id,
            DNSRecord.type == "A"
        )
    )
    dns_records = dns_result.scalars().all()
    
    # Get active/pending certificates
    certs_result = await db.execute(
        select(Certificate).where(
            Certificate.domain_id == domain_id,
            Certificate.status.in_([CertificateStatus.ISSUED, CertificateStatus.PENDING])
        )
    )
    active_certs = certs_result.scalars().all()
    
    covered_domains = {cert.common_name for cert in active_certs if cert.common_name}
    
    # Group by subdomain
    subdomains_map = {}
    for record in dns_records:
        if record.name not in subdomains_map:
            subdomains_map[record.name] = {
                "proxied": record.proxied,
                "dns_record_id": record.id,
                "count": 1
            }
        else:
            if record.proxied:
                subdomains_map[record.name]["proxied"] = True
            subdomains_map[record.name]["count"] += 1
    
    available = []
    for subdomain, info in subdomains_map.items():
        fqdn = domain.name if subdomain == "@" else f"{subdomain}.{domain.name}"
        
        if fqdn not in covered_domains:
            available.append({
                "subdomain": subdomain,
                "fqdn": fqdn,
                "dns_record_id": info["dns_record_id"],
                "proxied": info["proxied"],
                "records_count": info["count"]
            })
    
    available.sort(key=lambda x: (x["subdomain"] != "@", x["subdomain"]))
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
    # Выпустить Let's Encrypt SSL сертификат
    
    Автоматически выпускает бесплатный SSL сертификат от Let's Encrypt.
    
    ## Параметры:
    - `subdomain`: `@` для основного домена, или имя поддомена (www, api, etc.)
    - `email`: Email для уведомлений от Let's Encrypt (опционально)
    """
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    
    # Build FQDN
    if subdomain == "@":
        fqdn = domain.name
    else:
        # Verify A record exists
        dns_result = await db.execute(
            select(DNSRecord).where(
                DNSRecord.domain_id == domain_id,
                DNSRecord.name == subdomain,
                DNSRecord.type == "A"
            )
        )
        dns_record = dns_result.scalar_one_or_none()
        if not dns_record:
            raise HTTPException(
                status_code=404, 
                detail=f"DNS A record '{subdomain}' not found"
            )
        fqdn = f"{subdomain}.{domain.name}"
    
    # Check for existing certificate
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
    
    # Create pending certificate
    cert = Certificate(
        domain_id=domain_id,
        type=CertificateType.ACME,
        status=CertificateStatus.PENDING,
        common_name=fqdn,
        auto_renew=True,
        acme_challenge_type="http-01"
    )
    db.add(cert)
    await db.commit()
    await db.refresh(cert)
    
    # Add initial log
    log_entry = CertificateLog(
        certificate_id=cert.id,
        level=CertificateLogLevel.INFO,
        message=f"Certificate issuance started for {fqdn}",
        details=f'{{"subdomain": "{subdomain}", "email": "{email or settings.ACME_EMAIL}"}}'
    )
    db.add(log_entry)
    await db.commit()
    
    # Start background task
    from app.tasks.certificate_tasks import issue_single_certificate
    issue_single_certificate.delay(cert.id, email)
    
    return JSONResponse({
        "status": "pending",
        "message": f"Certificate issuance started for {fqdn}",
        "certificate_id": cert.id,
        "fqdn": fqdn
    })


@router.get("/{domain_id}/certificates/{cert_id}")
async def get_certificate(
    domain_id: int,
    cert_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_optional_current_user)
):
    """
    # Получить детальную информацию о сертификате
    """
    cert_result = await db.execute(
        select(Certificate).where(
            Certificate.id == cert_id,
            Certificate.domain_id == domain_id
        )
    )
    cert = cert_result.scalar_one_or_none()
    
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    
    return {
        "id": cert.id,
        "common_name": cert.common_name,
        "status": cert.status.value,
        "type": cert.type.value,
        "issuer": cert.issuer,
        "subject": cert.subject,
        "not_before": cert.not_before.isoformat() if cert.not_before else None,
        "not_after": cert.not_after.isoformat() if cert.not_after else None,
        "auto_renew": cert.auto_renew,
        "renew_before_days": cert.renew_before_days,
        "last_renewed_at": cert.last_renewed_at.isoformat() if cert.last_renewed_at else None,
        "created_at": cert.created_at.isoformat()
    }


@router.get("/{domain_id}/certificates/{cert_id}/logs")
async def get_certificate_logs(
    domain_id: int,
    cert_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_optional_current_user)
):
    """
    # Получить логи выпуска/обновления сертификата
    """
    cert_result = await db.execute(
        select(Certificate).where(
            Certificate.id == cert_id,
            Certificate.domain_id == domain_id
        )
    )
    cert = cert_result.scalar_one_or_none()
    
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    
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


@router.post("/{domain_id}/certificates/{cert_id}/renew")
async def renew_certificate(
    domain_id: int,
    cert_id: int,
    force: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_optional_current_user)
):
    """
    # Перевыпустить (обновить) SSL сертификат
    
    ## Параметры:
    - `force`: При `true` перевыпускает независимо от срока действия
    """
    cert_result = await db.execute(
        select(Certificate).where(
            Certificate.id == cert_id,
            Certificate.domain_id == domain_id
        )
    )
    cert = cert_result.scalar_one_or_none()
    
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    
    if cert.type != CertificateType.ACME:
        raise HTTPException(
            status_code=400, 
            detail="Only ACME certificates can be renewed automatically"
        )
    
    if cert.status != CertificateStatus.ISSUED:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot renew certificate with status '{cert.status.value}'"
        )
    
    # Check for pending renewal
    pending_result = await db.execute(
        select(Certificate).where(
            Certificate.domain_id == domain_id,
            Certificate.common_name == cert.common_name,
            Certificate.status == CertificateStatus.PENDING
        )
    )
    if pending_result.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="Certificate renewal already in progress"
        )
    
    # Create new certificate for renewal
    new_cert = Certificate(
        domain_id=cert.domain_id,
        type=CertificateType.ACME,
        status=CertificateStatus.PENDING,
        common_name=cert.common_name,
        auto_renew=cert.auto_renew,
        renew_before_days=cert.renew_before_days,
        acme_challenge_type="http-01"
    )
    db.add(new_cert)
    await db.commit()
    await db.refresh(new_cert)
    
    # Add log
    log_entry = CertificateLog(
        certificate_id=new_cert.id,
        level=CertificateLogLevel.INFO,
        message=f"Manual certificate renewal triggered for {cert.common_name}",
        details=f'{{"old_certificate_id": {cert.id}, "force": {str(force).lower()}}}'
    )
    db.add(log_entry)
    await db.commit()
    
    # Start background task
    from app.tasks.certificate_tasks import issue_single_certificate
    issue_single_certificate.delay(new_cert.id)
    
    return JSONResponse({
        "status": "pending",
        "message": f"Certificate renewal started for {cert.common_name}",
        "old_certificate_id": cert.id,
        "new_certificate_id": new_cert.id,
        "common_name": cert.common_name
    })


@router.delete("/{domain_id}/certificates/{cert_id}")
async def delete_certificate(
    domain_id: int,
    cert_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_optional_current_user)
):
    """
    # Удалить сертификат
    
    **Важно:** Если это единственный активный сертификат для домена,
    HTTPS перестанет работать.
    """
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    
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
