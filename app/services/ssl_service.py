"""SSL/TLS certificate management service"""
import logging
from typing import List, Optional
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

from app.models.certificate import Certificate
from app.models.domain import Domain
from app.schemas.cdn import CertificateCreate

logger = logging.getLogger(__name__)


class SSLService:
    """Service for managing SSL/TLS certificates"""
    
    @staticmethod
    async def get_certificates(
        db: AsyncSession,
        domain_id: int
    ) -> List[Certificate]:
        """Get all certificates for domain"""
        query = select(Certificate).where(
            Certificate.domain_id == domain_id
        ).order_by(Certificate.created_at.desc())
        
        result = await db.execute(query)
        return list(result.scalars().all())
    
    @staticmethod
    async def get_certificate(
        db: AsyncSession,
        cert_id: int
    ) -> Optional[Certificate]:
        """Get certificate by ID"""
        result = await db.execute(
            select(Certificate).where(Certificate.id == cert_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_active_certificate(
        db: AsyncSession,
        domain_id: int
    ) -> Optional[Certificate]:
        """Get active certificate for domain"""
        from app.models.certificate import CertificateStatus
        
        result = await db.execute(
            select(Certificate).where(
                Certificate.domain_id == domain_id,
                Certificate.status == CertificateStatus.ISSUED
            ).order_by(Certificate.not_after.desc())
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def create_certificate(
        db: AsyncSession,
        domain_id: int,
        cert_data: CertificateCreate
    ) -> Certificate:
        """Create/upload certificate"""
        # Parse certificate to extract info
        cert_info = SSLService._parse_certificate(cert_data.cert_pem)
        
        from app.models.certificate import CertificateStatus, CertificateType
        
        # Parse cert_type string to enum
        cert_type_enum = CertificateType.ACME if cert_data.cert_type == "acme" else CertificateType.MANUAL
        
        certificate = Certificate(
            domain_id=domain_id,
            type=cert_type_enum,
            cert_pem=cert_data.cert_pem,
            key_pem=cert_data.key_pem,  # TODO: Encrypt before storing
            chain_pem=cert_data.chain_pem,
            status=CertificateStatus.ISSUED,
            common_name=domain.name if 'domain' in locals() else '',
            not_before=cert_info.get("not_before"),
            not_after=cert_info.get("not_after"),
            issuer=cert_info.get("issuer"),
            subject=cert_info.get("subject")
        )
        
        # Mark old certificates as expired
        old_certs = await db.execute(
            select(Certificate).where(
                Certificate.domain_id == domain_id,
                Certificate.status == CertificateStatus.ISSUED
            )
        )
        for old_cert in old_certs.scalars():
            old_cert.status = CertificateStatus.EXPIRED
        
        db.add(certificate)
        await db.commit()
        await db.refresh(certificate)
        
        return certificate
    
    @staticmethod
    async def request_acme_certificate(
        db: AsyncSession,
        domain_id: int,
        wildcard: bool = False
    ) -> Certificate:
        """Request Let's Encrypt certificate via ACME"""
        from app.models.certificate import CertificateStatus, CertificateType
        
        domain = await db.execute(
            select(Domain).where(Domain.id == domain_id)
        )
        domain = domain.scalar_one_or_none()
        
        if not domain:
            raise ValueError("Domain not found")
        
        certificate = Certificate(
            domain_id=domain_id,
            type=CertificateType.ACME,
            status=CertificateStatus.PENDING,
            common_name=domain.name,
            acme_challenge_type="dns-01" if wildcard else "http-01"
        )
        
        db.add(certificate)
        await db.commit()
        await db.refresh(certificate)
        
        # TODO: Trigger Celery task to obtain certificate
        # from app.tasks.certificate_tasks import obtain_acme_certificate
        # obtain_acme_certificate.delay(certificate.id)
        
        return certificate
    
    @staticmethod
    async def renew_certificate(
        db: AsyncSession,
        cert_id: int
    ) -> Optional[Certificate]:
        """Renew certificate"""
        from app.models.certificate import CertificateStatus, CertificateType
        
        cert = await SSLService.get_certificate(db, cert_id)
        if not cert:
            return None
        
        if cert.type != CertificateType.ACME:
            raise ValueError("Only ACME certificates can be auto-renewed")
        
        # TODO: Trigger renewal task
        cert.status = CertificateStatus.PENDING
        await db.commit()
        await db.refresh(cert)
        
        return cert
    
    @staticmethod
    async def delete_certificate(db: AsyncSession, cert_id: int) -> bool:
        """Delete certificate"""
        from app.models.certificate import CertificateStatus
        
        cert = await SSLService.get_certificate(db, cert_id)
        if not cert:
            return False
        
        if cert.status == CertificateStatus.ISSUED:
            raise ValueError("Cannot delete active certificate")
        
        await db.delete(cert)
        await db.commit()
        return True
    
    @staticmethod
    async def get_expiring_certificates(
        db: AsyncSession,
        days: int = 30
    ) -> List[Certificate]:
        """Get certificates expiring in X days"""
        from app.models.certificate import CertificateStatus
        
        expiry_date = datetime.utcnow() + timedelta(days=days)
        
        query = select(Certificate).where(
            Certificate.status == CertificateStatus.ISSUED,
            Certificate.not_after <= expiry_date,
            Certificate.not_after > datetime.utcnow()
        )
        
        result = await db.execute(query)
        return list(result.scalars().all())
    
    @staticmethod
    def _parse_certificate(cert_pem: str) -> dict:
        """Parse certificate PEM and extract information"""
        try:
            cert = x509.load_pem_x509_certificate(
                cert_pem.encode(),
                default_backend()
            )
            
            return {
                "not_before": cert.not_valid_before_utc,
                "not_after": cert.not_valid_after_utc,
                "issuer": cert.issuer.rfc4514_string(),
                "subject": cert.subject.rfc4514_string()
            }
        except Exception as e:
            logger.error(f"Failed to parse certificate: {e}")
            return {
                "not_before": None,
                "not_after": None,
                "issuer": "Unknown",
                "subject": "Unknown"
            }
    
    @staticmethod
    async def update_tls_settings(
        db: AsyncSession,
        domain_id: int,
        settings: dict
    ) -> bool:
        """Update TLS settings for domain"""
        domain = await db.execute(
            select(Domain).where(Domain.id == domain_id)
        )
        domain = domain.scalar_one_or_none()
        
        if not domain:
            return False
        
        # Update domain TLS settings
        for key, value in settings.items():
            if hasattr(domain, key):
                setattr(domain, key, value)
        
        await db.commit()
        return True
