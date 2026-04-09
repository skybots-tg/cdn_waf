"""SSL/TLS certificate management service"""
import logging
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

from app.models.certificate import Certificate
from app.models.domain import Domain
from app.schemas.cdn import CertificateCreate
from app.core.config import settings

logger = logging.getLogger(__name__)


class SSLService:
    """Service for managing SSL/TLS certificates"""
    
    @staticmethod
    def _normalize_cert_dt(dt: datetime | None) -> datetime | None:
        """Приводим datetime к наивному UTC, чтобы asyncpg не орал."""
        if dt is None:
            return None
        if isinstance(dt, datetime) and dt.tzinfo is not None:
            # приводим к UTC и выкидываем tzinfo
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    
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
        # Verify domain exists
        domain_res = await db.execute(
            select(Domain).where(Domain.id == domain_id)
        )
        domain = domain_res.scalar_one_or_none()
        if not domain:
            raise ValueError(f"Domain {domain_id} not found")
        
        # Parse certificate to extract info
        cert_info = SSLService._parse_certificate(cert_data.cert_pem)
        
        from app.models.certificate import CertificateStatus, CertificateType
        
        # Parse cert_type string to enum
        if isinstance(cert_data.cert_type, str):
            cert_type_enum = (
                CertificateType.ACME
                if cert_data.cert_type.lower() == "acme"
                else CertificateType.MANUAL
            )
        else:
            cert_type_enum = cert_data.cert_type
        
        from app.services.crypto_service import CryptoService
        encrypted_key = CryptoService.encrypt(cert_data.key_pem)

        certificate = Certificate(
            domain_id=domain_id,
            type=cert_type_enum,
            cert_pem=cert_data.cert_pem,
            key_pem=encrypted_key,
            chain_pem=cert_data.chain_pem,
            status=CertificateStatus.ISSUED,
            common_name=domain.name,
            not_before=cert_info.get("not_before"),
            not_after=cert_info.get("not_after"),
            issuer=cert_info.get("issuer"),
            subject=cert_info.get("subject")
        )
        
        # Mark old certificates as expired
        old_certs_result = await db.execute(
            select(Certificate).where(
                Certificate.domain_id == domain_id,
                Certificate.status == CertificateStatus.ISSUED
            )
        )
        for old_cert in old_certs_result.scalars():
            old_cert.status = CertificateStatus.EXPIRED
        
        db.add(certificate)
        await db.commit()
        await db.refresh(certificate)
        
        return certificate
    
    # ACME methods are delegated to AcmeService (app.services.acme_service)
    # These thin wrappers preserve backward-compatibility for existing callers.

    @staticmethod
    async def process_acme_order(db: AsyncSession, domain_id: int):
        from app.services.acme_service import AcmeService
        return await AcmeService.process_acme_order(db, domain_id)

    @staticmethod
    async def process_single_acme_order(db: AsyncSession, certificate_id: int, email: str = None):
        from app.services.acme_service import AcmeService
        return await AcmeService.process_single_acme_order(db, certificate_id, email)

    @staticmethod
    async def request_acme_certificate(db: AsyncSession, domain_id: int, wildcard: bool = False):
        from app.services.acme_service import AcmeService
        return await AcmeService.request_acme_certificate(db, domain_id, wildcard)

    @staticmethod
    async def renew_certificate(db: AsyncSession, cert_id: int):
        from app.services.acme_service import AcmeService
        return await AcmeService.renew_certificate(db, cert_id)
    
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
        from datetime import timezone
        
        now = datetime.now(timezone.utc)
        expiry_date = now + timedelta(days=days)
        
        query = select(Certificate).where(
            Certificate.status == CertificateStatus.ISSUED,
            Certificate.not_after <= expiry_date,
            Certificate.not_after > now
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
            
            # Fallback for older cryptography versions
            not_before = getattr(cert, "not_valid_before_utc", cert.not_valid_before)
            not_after = getattr(cert, "not_valid_after_utc", cert.not_valid_after)
            
            return {
                "not_before": SSLService._normalize_cert_dt(not_before),
                "not_after": SSLService._normalize_cert_dt(not_after),
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
        tls_settings_dict: dict
    ) -> bool:
        """Update TLS settings for domain"""
        from app.models.domain import DomainTLSSettings
        
        # Get or create TLS settings
        result = await db.execute(
            select(DomainTLSSettings).where(DomainTLSSettings.domain_id == domain_id)
        )
        tls_settings = result.scalar_one_or_none()
        
        if not tls_settings:
            domain_result = await db.execute(
                select(Domain).where(Domain.id == domain_id)
            )
            domain = domain_result.scalar_one_or_none()
            if not domain:
                return False
            
            tls_settings = DomainTLSSettings(domain_id=domain_id)
            db.add(tls_settings)
        
        for key, value in tls_settings_dict.items():
            if hasattr(tls_settings, key):
                setattr(tls_settings, key, value)
        
        await db.commit()
        return True