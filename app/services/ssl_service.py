"""SSL/TLS certificate management service"""
import logging
import base64
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

        # 2. Load or Generate Account Key
        import os
        from pathlib import Path
        
        account_key_path = Path(settings.ACME_ACCOUNT_KEY_PATH)
        account_key_path.parent.mkdir(parents=True, exist_ok=True)
        
        if account_key_path.exists():
            # Load existing account key
            logger.info(f"Loading existing ACME account key from {account_key_path}")
            with open(account_key_path, 'rb') as f:
                acc_key_crypto = serialization.load_pem_private_key(
                    f.read(),
                    password=None,
                    backend=default_backend()
                )
        else:
            # Generate new account key
            logger.info(f"Generating new ACME account key and saving to {account_key_path}")
            acc_key_crypto = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            )
            # Save it for future use
            with open(account_key_path, 'wb') as f:
                f.write(acc_key_crypto.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption()
                ))
            logger.info("ACME account key saved")
        
        # Wrap the key in josepy JWK format for acme library
        acc_key = jose.JWKRSA(key=acc_key_crypto)
        
        # 3. Initialize ACME Client and Register/Query Account
        logger.info(f"Connecting to ACME server: {settings.ACME_DIRECTORY_URL}")
        net = acme.client.ClientNetwork(acc_key, user_agent="FlareCloud/1.0")
        directory = acme.messages.Directory.from_json(
            net.get(settings.ACME_DIRECTORY_URL).json()
        )
        client = acme.client.ClientV2(directory, net)
        logger.info("ACME client initialized")
        
        # Try to register or query existing account
        try:
            if account_key_path.exists():
                # Key exists, account probably already registered - query it
                regr = client.new_account(
                    acme.messages.NewRegistration.from_data(
                        email=settings.ACME_EMAIL,
                        terms_of_service_agreed=True,
                        only_return_existing=True  # Don't create new, just query
                    )
                )
                logger.info("Using existing ACME account")
            else:
                # New key, register new account
                regr = client.new_account(
                    acme.messages.NewRegistration.from_data(
                        email=settings.ACME_EMAIL,
                        terms_of_service_agreed=True
                    )
                )
                logger.info("New ACME account registered successfully")
        except Exception as e:
            logger.warning(f"Account operation warning: {e}")
            # Continue anyway - the client is initialized with the key
        
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
            
            token_str = SSLService._http01_token_str(http_challenge)
            validation_str = SSLService._http01_validation_str(validation)
            
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
                "not_before": SSLService._normalize_cert_dt(
                    getattr(leaf_cert, "not_valid_before_utc", leaf_cert.not_valid_before)
                ),
                "not_after": SSLService._normalize_cert_dt(
                    getattr(leaf_cert, "not_valid_after_utc", leaf_cert.not_valid_after)
                ),
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
            encryption_algorithm=serialization.NoEncryption(),
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
    def _http01_token_str(http_challenge) -> str:
        """
        Вернуть токен HTTP-01 в том виде, в каком его видит ACME-сервер:
        base64url без '='. Совместимо с текущими версиями acme-python.
        """
        # нам может прийти ChallengeBody (authz.challenges[i]) или сам HTTP01
        chall = getattr(http_challenge, "chall", http_challenge)

        # Нормальный путь — использовать encode("token"), как в acme.standalone.HTTP01RequestHandler
        try:
            token = chall.encode("token")  # вернёт base64url-строку для поля token
            if isinstance(token, bytes):
                return token.decode("ascii")
            return token
        except Exception:
            # Фолбэк на случай странной версии/реализации
            token_raw = getattr(chall, "token", None)
            if isinstance(token_raw, bytes):
                # base64url без padding, как в ACME
                return base64.urlsafe_b64encode(token_raw).decode("ascii").rstrip("=")
            return str(token_raw)

    @staticmethod
    def _http01_validation_str(validation) -> str:
        """
        Привести validation (key-authorization) к str безопасно.
        """
        if isinstance(validation, bytes):
            return validation.decode("utf-8", errors="ignore")
        return str(validation)
    
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
    
    @staticmethod
    async def process_single_acme_order(
        db: AsyncSession,
        certificate_id: int,
        email: str = None
    ):
        """
        Process ACME certificate order for a single certificate (one subdomain)
        This is optimized version that issues certificate for specific FQDN only
        """
        from app.models.certificate import Certificate, CertificateStatus
        from app.models.domain import Domain
        from app.models.certificate_log import CertificateLog, CertificateLogLevel
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
        
        def add_log(level: CertificateLogLevel, message: str, details: str = None):
            """Helper to add log entry"""
            log_entry = CertificateLog(
                certificate_id=certificate_id,
                level=level,
                message=message,
                details=details
            )
            db.add(log_entry)
        
        # 1. Get certificate record
        cert = await db.execute(select(Certificate).where(Certificate.id == certificate_id))
        cert = cert.scalar_one_or_none()
        if not cert:
            logger.error(f"Certificate {certificate_id} not found")
            return
        
        # Get domain
        domain = await db.execute(select(Domain).where(Domain.id == cert.domain_id))
        domain = domain.scalar_one_or_none()
        if not domain:
            logger.error(f"Domain {cert.domain_id} not found")
            cert.status = CertificateStatus.FAILED
            add_log(CertificateLogLevel.ERROR, f"Domain not found")
            await db.commit()
            return
        
        # Use certificate's common_name as the only identifier
        fqdn = cert.common_name
        identifiers_list = [fqdn]
        
        add_log(CertificateLogLevel.INFO, f"Starting certificate issuance for {fqdn}")
        await db.commit()
        
        logger.info(f"Requesting certificate for: {fqdn}")

        # 2. Load or Generate Account Key
        import os
        from pathlib import Path
        
        account_key_path = Path(settings.ACME_ACCOUNT_KEY_PATH)
        account_key_path.parent.mkdir(parents=True, exist_ok=True)
        
        if account_key_path.exists():
            logger.info(f"Loading existing ACME account key")
            with open(account_key_path, 'rb') as f:
                acc_key_crypto = serialization.load_pem_private_key(
                    f.read(),
                    password=None,
                    backend=default_backend()
                )
        else:
            logger.info(f"Generating new ACME account key")
            acc_key_crypto = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            )
            with open(account_key_path, 'wb') as f:
                f.write(acc_key_crypto.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption()
                ))
            add_log(CertificateLogLevel.INFO, "Generated new ACME account key")
            await db.commit()
        
        # Wrap the key in josepy JWK format
        acc_key = jose.JWKRSA(key=acc_key_crypto)
        
        # 3. Initialize ACME Client
        add_log(CertificateLogLevel.INFO, f"Connecting to ACME server: {settings.ACME_DIRECTORY_URL}")
        await db.commit()
        
        logger.info(f"Connecting to ACME server: {settings.ACME_DIRECTORY_URL}")
        net = acme.client.ClientNetwork(acc_key, user_agent="FlareCloud/1.0")
        directory = acme.messages.Directory.from_json(
            net.get(settings.ACME_DIRECTORY_URL).json()
        )
        client = acme.client.ClientV2(directory, net)
        
        # Register or query account (ACME v2, 2025)
        acme_email = email or settings.ACME_EMAIL
        regr = None
        try:
            if account_key_path.exists():
                # Ключ есть, пробуем получить уже существующий аккаунт
                try:
                    regr = client.new_account(
                        acme.messages.NewRegistration.from_data(
                            email=acme_email,
                            terms_of_service_agreed=True,
                            only_return_existing=True
                        )
                    )
                    # Если сюда дошло — сервер вернул 201/201 и аккаунт создан сейчас
                    add_log(CertificateLogLevel.INFO, "Using existing ACME account (new_account returned successfully)")
                    await db.commit()
                except acme.errors.ConflictError as conflict_error:
                    # Для ACME v2: 200 + Location → ConflictError с location = account URL
                    logger.info(f"ACME account already exists (ConflictError): {conflict_error}")
                    account_uri = getattr(conflict_error, "location", str(conflict_error).strip())
                    # Минимальное тело регистрации: достаточно email, key подтянется с сервера
                    reg_body = acme.messages.Registration.from_data(email=acme_email)
                    regr = acme.messages.RegistrationResource(
                        uri=account_uri,
                        body=reg_body,
                    )
                    # ВАЖНО: чтобы дальше все запросы шли с kid
                    client.net.account = regr
                    add_log(
                        CertificateLogLevel.INFO,
                        "Using existing ACME account (resolved from ConflictError)"
                    )
                    await db.commit()
                except Exception as account_error:
                    # ACME v2: если only_return_existing=true, а аккаунта нет,
                    # сервер может вернуть accountDoesNotExist
                    if "accountDoesNotExist" in str(account_error):
                        logger.info("ACME account doesn't exist, creating new one")
                        regr = client.new_account(
                            acme.messages.NewRegistration.from_data(
                                email=acme_email,
                                terms_of_service_agreed=True
                            )
                        )
                        # ClientV2.new_account сам положит результат в client.net.account
                        add_log(
                            CertificateLogLevel.SUCCESS,
                            f"ACME account created with email: {acme_email}"
                        )
                        await db.commit()
                    else:
                        logger.warning(f"Account operation warning: {account_error}")
                        add_log(
                            CertificateLogLevel.WARNING,
                            f"Account operation warning: {str(account_error)}"
                        )
                        await db.commit()
                        raise
            else:
                # Ключа не было (теоретически), создали выше — регистрируем новый аккаунт
                try:
                    regr = client.new_account(
                        acme.messages.NewRegistration.from_data(
                            email=acme_email,
                            terms_of_service_agreed=True
                        )
                    )
                    # new_account сам поставит client.net.account
                    add_log(
                        CertificateLogLevel.SUCCESS,
                        f"ACME account registered with email: {acme_email}"
                    )
                    await db.commit()
                except acme.errors.ConflictError as conflict_error:
                    # Редкий кейс: аккаунт уже есть, а мы думали, что его нет
                    logger.info(f"ACME account already exists (ConflictError): {conflict_error}")
                    account_uri = getattr(conflict_error, "location", str(conflict_error).strip())
                    reg_body = acme.messages.Registration.from_data(email=acme_email)
                    regr = acme.messages.RegistrationResource(
                        uri=account_uri,
                        body=reg_body,
                    )
                    client.net.account = regr
                    add_log(
                        CertificateLogLevel.INFO,
                        "Using existing ACME account (resolved conflict in no-key branch)"
                    )
                    await db.commit()
        except Exception as e:
            # Финальный фолбэк: аккаунт вообще не получили
            if regr is None:
                logger.error(f"Failed to register/retrieve ACME account: {e}", exc_info=True)
                add_log(
                    CertificateLogLevel.ERROR,
                    f"Failed to register ACME account: {str(e)}"
                )
                cert.status = CertificateStatus.FAILED
                await db.commit()
                return
        # На всякий случай: если net.account не выставлен, а regr есть — выставим
        if client.net.account is None and regr is not None:
            client.net.account = regr
        
        # 4. Generate Certificate Key and CSR
        add_log(CertificateLogLevel.INFO, "Generating certificate key and CSR")
        await db.commit()
        
        pkey = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )
        
        # Build CSR
        san_dns_names = [x509.DNSName(fqdn)]
        
        csr_builder = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, fqdn),
        ]))
        
        csr_builder = csr_builder.add_extension(
            x509.SubjectAlternativeName(san_dns_names),
            critical=False,
        )
        
        csr = csr_builder.sign(pkey, hashes.SHA256(), default_backend())
        csr_pem = csr.public_bytes(serialization.Encoding.PEM)
        
        # Create Order
        add_log(CertificateLogLevel.INFO, "Creating ACME order")
        await db.commit()
        
        logger.info("Creating certificate order")
        try:
            order = client.new_order(csr_pem)
            add_log(CertificateLogLevel.SUCCESS, f"ACME order created successfully")
            await db.commit()
        except Exception as e:
            logger.error(f"Failed to create ACME order: {e}", exc_info=True)
            add_log(CertificateLogLevel.ERROR, f"Failed to create ACME order: {str(e)}")
            cert.status = CertificateStatus.FAILED
            await db.commit()
            return
        
        # 5. Process Authorizations
        add_log(CertificateLogLevel.INFO, f"Processing authorization for {fqdn}")
        await db.commit()
        
        logger.info(f"Processing authorization")
        for authz_resource in order.authorizations:
            authz_url = authz_resource.uri if hasattr(authz_resource, 'uri') else str(authz_resource)
            logger.info(f"Fetching authorization from {authz_url}")
            
            try:
                response = client._post_as_get(authz_url)
                authz = acme.messages.Authorization.from_json(response.json())
            except Exception as e:
                logger.error(f"Failed to fetch authorization: {e}", exc_info=True)
                add_log(CertificateLogLevel.ERROR, f"Failed to fetch authorization: {str(e)}")
                cert.status = CertificateStatus.FAILED
                await db.commit()
                return
            
            # Find HTTP-01 challenge
            http_challenge = None
            for chall in authz.challenges:
                if isinstance(chall.chall, acme.challenges.HTTP01):
                    http_challenge = chall
                    break
            
            if not http_challenge:
                logger.error("No HTTP-01 challenge found")
                cert.status = CertificateStatus.FAILED
                add_log(CertificateLogLevel.ERROR, "No HTTP-01 challenge found in authorization")
                await db.commit()
                return

            # 6. Set Challenge Token/Response
            response, validation = http_challenge.response_and_validation(acc_key)
            
            # Каноничный токен и validation с учётом байтов/строк
            token_str = SSLService._http01_token_str(http_challenge)
            validation_str = SSLService._http01_validation_str(validation)
            
            add_log(CertificateLogLevel.INFO, f"Storing HTTP-01 challenge token for domain {fqdn}")
            await db.commit()
            
            logger.info(f"Storing challenge token: {token_str[:30]}...")
            
            from app.core.redis import redis_client
            if redis_client:
                await redis_client.set(
                    f"acme:challenge:{token_str}", 
                    validation_str,
                    expire=3600
                )
                logger.info(f"Challenge stored in Redis")
            else:
                logger.error("Redis not available")
                cert.status = CertificateStatus.FAILED
                add_log(CertificateLogLevel.ERROR, "Redis not available for challenge storage")
                await db.commit()
                return

            # 7. Trigger Validation
            challenge_url = f"http://{fqdn}/.well-known/acme-challenge/{token_str}"
            add_log(
                CertificateLogLevel.INFO, 
                f"Requesting ACME validation for {fqdn}",
                f"Let's Encrypt will check: {challenge_url}"
            )
            await db.commit()
            
            logger.info(f"Let's Encrypt will validate: {challenge_url}")
            logger.info(f"Expected validation response: {validation_str[:50]}...")
            
            try:
                client.answer_challenge(http_challenge, response)
                add_log(CertificateLogLevel.INFO, f"Challenge answer sent to ACME server")
                await db.commit()
            except Exception as e:
                logger.error(f"Failed to answer challenge: {e}", exc_info=True)
                add_log(CertificateLogLevel.ERROR, f"Failed to answer challenge: {str(e)}")
                cert.status = CertificateStatus.FAILED
                await db.commit()
                return
            
            # 8. Wait for validation
            import time
            for attempt in range(10):
                time.sleep(2)
                try:
                    response = client._post_as_get(authz_url)
                    authz_status = acme.messages.Authorization.from_json(response.json())
                    
                    logger.info(f"Validation attempt {attempt + 1}/10: status={authz_status.status}")
                    
                    # Log detailed error information if validation fails
                    if authz_status.status == acme.messages.STATUS_INVALID:
                        for chall in authz_status.challenges:
                            if hasattr(chall, 'error') and chall.error:
                                logger.error(f"Challenge error: {chall.error}")
                                add_log(
                                    CertificateLogLevel.ERROR,
                                    f"ACME validation error: {chall.error.get('detail', str(chall.error))}",
                                    str(chall.error)
                                )
                    
                except Exception as e:
                    logger.error(f"Failed to check authorization status (attempt {attempt + 1}): {e}")
                    add_log(CertificateLogLevel.WARNING, f"Failed to check status (attempt {attempt + 1}): {str(e)}")
                    await db.commit()
                    continue
                
                if authz_status.status == acme.messages.STATUS_VALID:
                    logger.info(f"Authorization validated successfully for {fqdn}")
                    add_log(CertificateLogLevel.SUCCESS, f"Authorization validated successfully for {fqdn}")
                    await db.commit()
                    break
                elif authz_status.status == acme.messages.STATUS_INVALID:
                    logger.error(f"Authorization failed for {fqdn}: {authz_status}")
                    cert.status = CertificateStatus.FAILED
                    add_log(CertificateLogLevel.ERROR, f"Authorization INVALID for {fqdn}", str(authz_status))
                    await db.commit()
                    return
                
                if attempt < 9:
                    add_log(CertificateLogLevel.INFO, f"Waiting for validation (attempt {attempt + 1}/10), current status: {authz_status.status}")
                    await db.commit()
            else:
                logger.error(f"Authorization timeout for {fqdn} after 10 attempts")
                cert.status = CertificateStatus.FAILED
                add_log(
                    CertificateLogLevel.ERROR, 
                    f"Authorization timeout for {fqdn}",
                    f"Let's Encrypt could not validate {challenge_url}. Please ensure the domain points to this server and port 80 is accessible."
                )
                await db.commit()
                return

        # 9. Finalize Order
        add_log(CertificateLogLevel.INFO, "Finalizing certificate order")
        await db.commit()
        
        logger.info("Finalizing order")
        try:
            finalized_order = client.poll_and_finalize(order)
        except Exception as e:
            logger.error(f"Failed to finalize order: {e}", exc_info=True)
            add_log(CertificateLogLevel.ERROR, f"Failed to finalize certificate order: {str(e)}")
            cert.status = CertificateStatus.FAILED
            await db.commit()
            return
        
        # 10. Save Certificate
        fullchain_pem = finalized_order.fullchain_pem
        
        # Parse leaf certificate
        try:
            pem_start = "-----BEGIN CERTIFICATE-----"
            pem_end = "-----END CERTIFICATE-----"
            start_idx = fullchain_pem.find(pem_start)
            end_idx = fullchain_pem.find(pem_end)
            if start_idx == -1 or end_idx == -1:
                raise ValueError("Invalid fullchain_pem")
            first_cert_pem = fullchain_pem[start_idx:end_idx + len(pem_end)] + "\n"
            leaf_cert = x509.load_pem_x509_certificate(
                first_cert_pem.encode(),
                default_backend()
            )
            cert_info = {
                "not_before": SSLService._normalize_cert_dt(
                    getattr(leaf_cert, "not_valid_before_utc", leaf_cert.not_valid_before)
                ),
                "not_after": SSLService._normalize_cert_dt(
                    getattr(leaf_cert, "not_valid_after_utc", leaf_cert.not_valid_after)
                ),
                "issuer": leaf_cert.issuer.rfc4514_string(),
                "subject": leaf_cert.subject.rfc4514_string(),
            }
        except Exception as e:
            logger.error(f"Failed to parse certificate: {e}")
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
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        cert.status = CertificateStatus.ISSUED
        cert.not_before = cert_info["not_before"]
        cert.not_after = cert_info["not_after"]
        cert.issuer = cert_info["issuer"]
        cert.subject = cert_info["subject"]
        
        add_log(
            CertificateLogLevel.SUCCESS, 
            f"Certificate issued successfully for {fqdn}",
            f"Valid until: {cert_info['not_after']}"
        )
        
        await db.commit()
        logger.info(f"Certificate issued successfully for {fqdn}")