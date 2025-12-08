"""SSL/TLS certificate management service"""
import logging
import base64
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
        
        certificate = Certificate(
            domain_id=domain_id,
            type=cert_type_enum,
            cert_pem=cert_data.cert_pem,
            key_pem=cert_data.key_pem,  # TODO: Encrypt before storing
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
    
    @staticmethod
    async def process_acme_order(
        db: AsyncSession,
        domain_id: int
    ):
        """Process ACME certificate order"""
        from app.models.certificate import Certificate, CertificateStatus
        from app.models.domain import Domain
        from app.core.config import settings
        import acme.client
        import acme.messages
        import acme.challenges
        import josepy as jose
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes
        
        from app.models.dns import DNSRecord
        
        # 1. Get domain and certificate record
        domain = await db.execute(select(Domain).where(Domain.id == domain_id))
        domain = domain.scalar_one_or_none()
        if not domain:
            logger.error(f"Domain {domain_id} not found for ACME processing")
            return

        # Fetch subdomains from DNS (for SANs)
        dns_records_result = await db.execute(
            select(DNSRecord).where(
                DNSRecord.domain_id == domain.id,
                DNSRecord.type == "A"
            )
        )
        dns_records = dns_records_result.scalars().all()
        
        # Determine SANs (Subject Alternative Names)
        sans = set()
        sans.add(domain.name) # Always include root
        for r in dns_records:
            if r.proxied: # Only include proxied records
                if r.name == "@":
                    sans.add(domain.name)
                else:
                    sans.add(f"{r.name}.{domain.name}")
        
        # Convert to list and ensure unique
        identifiers_list = sorted(list(sans))
        logger.info(f"Requesting certificate for: {identifiers_list}")

        cert = await db.execute(
            select(Certificate).where(
                Certificate.domain_id == domain_id, 
                Certificate.status == CertificateStatus.PENDING
            ).order_by(Certificate.created_at.desc())
        )
        cert = cert.scalar_one_or_none()
        if not cert:
            logger.warning(f"No pending certificate found for domain {domain.name}")
            return

        # 2. Generate Account Key
        acc_key_crypto = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )
        # Wrap the key in josepy JWK format for acme library
        acc_key = jose.JWKRSA(key=acc_key_crypto)
        
        # 3. Register Account
        logger.info(f"Connecting to ACME server: {settings.ACME_DIRECTORY_URL}")
        net = acme.client.ClientNetwork(acc_key, user_agent="FlareCloud/1.0")
        directory = acme.messages.Directory.from_json(
            net.get(settings.ACME_DIRECTORY_URL).json()
        )
        client = acme.client.ClientV2(directory, net)
        logger.info("ACME client initialized")
        
        try:
            regr = client.new_account(
                acme.messages.NewRegistration.from_data(
                    email=settings.ACME_EMAIL,
                    terms_of_service_agreed=True
                )
            )
            logger.info("ACME account registered successfully")
        except Exception as e:
            # Assuming account already exists, we would look it up, but simplified here
            # In production, store account key persistently!
            logger.warning(f"Account registration warning (might exist): {e}")
            # If it exists, we proceed (acme lib handles key reuse usually if initialized correctly)
            # But here we generated a NEW key, so we are registering a NEW account.
        
        # 4. Generate Certificate Key and CSR first (required for acme 2.x)
        pkey = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )
        
        # Build CSR with SANs
        common_name = identifiers_list[0]
        san_dns_names = [x509.DNSName(name) for name in identifiers_list]
        
        csr_builder = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]))
        
        # Add SAN extension
        csr_builder = csr_builder.add_extension(
            x509.SubjectAlternativeName(san_dns_names),
            critical=False,
        )
        
        csr = csr_builder.sign(pkey, hashes.SHA256(), default_backend())
        csr_pem = csr.public_bytes(serialization.Encoding.PEM)
        
        # Create Order with CSR
        logger.info("Creating certificate order")
        order = client.new_order(csr_pem)
        
        # 5. Process Authorizations
        logger.info(f"Processing {len(order.authorizations)} authorizations")
        for authz_resource in order.authorizations:
            # Extract URL from AuthorizationResource object
            authz_url = authz_resource.uri if hasattr(authz_resource, 'uri') else str(authz_resource)
            logger.info(f"Fetching authorization from {authz_url}")
            # Fetch authorization using POST-as-GET
            response = client._post_as_get(authz_url)
            authz = acme.messages.Authorization.from_json(response.json())
            # Find HTTP-01 challenge
            http_challenge = None
            for chall in authz.challenges:
                if isinstance(chall.chall, acme.challenges.HTTP01):
                    http_challenge = chall
                    break
            
            if not http_challenge:
                logger.error("No HTTP-01 challenge found")
                cert.status = CertificateStatus.FAILED
                await db.commit()
                return

            # 6. Set Challenge Token/Response
            response, validation = http_challenge.response_and_validation(acc_key)
            
            # ACME tokens are raw bytes that need to be base64url encoded
            # This is the format expected in URLs and by Let's Encrypt
            token_raw = http_challenge.chall.token
            if isinstance(token_raw, bytes):
                # Encode to base64url (URL-safe base64 without padding)
                token_str = base64.urlsafe_b64encode(token_raw).decode('ascii').rstrip('=')
            else:
                token_str = str(token_raw)
            
            # Validation might be bytes from josepy, decode it
            if isinstance(validation, bytes):
                validation_str = validation.decode('utf-8')
            else:
                validation_str = str(validation)
            
            logger.info(f"Storing challenge token: {token_str[:30]}... for domain {authz.identifier.value}")
            logger.info(f"Full token: {token_str}")
            
            from app.core.redis import redis_client
            if redis_client:
                # Store token -> validation mapping
                await redis_client.set(
                    f"acme:challenge:{token_str}", 
                    validation_str,
                    expire=3600
                )
                logger.info(f"Challenge stored in Redis: acme:challenge:{token_str}")
            else:
                logger.error("Redis not available for ACME challenge storage")
                cert.status = CertificateStatus.FAILED
                await db.commit()
                return

            # 7. Trigger Validation
            client.answer_challenge(http_challenge, response)
            
            # 8. Wait for valid status - poll the authorization URL again
            import time
            for _ in range(10):  # Try 10 times
                time.sleep(2)  # Wait 2 seconds between polls
                response = client._post_as_get(authz_url)
                authz_status = acme.messages.Authorization.from_json(response.json())
                if authz_status.status == acme.messages.STATUS_VALID:
                    logger.info(f"Authorization validated successfully for {authz.identifier.value}")
                    break
                elif authz_status.status == acme.messages.STATUS_INVALID:
                    logger.error(f"Authorization failed for {authz.identifier.value}: {authz_status}")
                    cert.status = CertificateStatus.FAILED
                    await db.commit()
                    return
            else:
                logger.error(f"Authorization timeout for {authz.identifier.value}")
                cert.status = CertificateStatus.FAILED
                await db.commit()
                return

        # 9. Finalize Order (already have CSR from earlier)
        logger.info("Finalizing order")
        finalized_order = client.poll_and_finalize(order)
        
        # 10. Save Certificate
        fullchain_pem = finalized_order.fullchain_pem
        
        # Parse leaf certificate from fullchain to extract validity dates
        try:
            pem_start = "-----BEGIN CERTIFICATE-----"
            pem_end = "-----END CERTIFICATE-----"
            start_idx = fullchain_pem.find(pem_start)
            end_idx = fullchain_pem.find(pem_end)
            if start_idx == -1 or end_idx == -1:
                raise ValueError("Invalid fullchain_pem, cannot find certificate boundaries")
            first_cert_pem = fullchain_pem[start_idx:end_idx + len(pem_end)] + "\n"
            leaf_cert = x509.load_pem_x509_certificate(
                first_cert_pem.encode(),
                default_backend()
            )
            cert_info = {
                "not_before": getattr(leaf_cert, "not_valid_before_utc", leaf_cert.not_valid_before),
                "not_after": getattr(leaf_cert, "not_valid_after_utc", leaf_cert.not_valid_after),
                "issuer": leaf_cert.issuer.rfc4514_string(),
                "subject": leaf_cert.subject.rfc4514_string(),
            }
        except Exception as e:
            logger.error(f"Failed to parse leaf certificate from fullchain: {e}")
            cert_info = {
                "not_before": None,
                "not_after": None,
                "issuer": "Unknown",
                "subject": "Unknown",
            }
        
        cert.cert_pem = fullchain_pem
        cert.key_pem = pkey.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption=serialization.NoEncryption()
        ).decode()
        cert.status = CertificateStatus.ISSUED
        cert.not_before = cert_info["not_before"]
        cert.not_after = cert_info["not_after"]
        cert.issuer = cert_info["issuer"]
        cert.subject = cert_info["subject"]
        
        await db.commit()
        logger.info(f"Certificate issued successfully for {domain.name}")

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
        
        # Trigger Celery task to obtain certificate
        from app.tasks.certificate_tasks import issue_certificate
        issue_certificate.delay(domain_id)
        
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
                "not_before": not_before,
                "not_after": not_after,
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
