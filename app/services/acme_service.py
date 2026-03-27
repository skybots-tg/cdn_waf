"""ACME certificate issuance service (Let's Encrypt)"""
import asyncio
import base64
import logging
from typing import Optional

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.certificate import Certificate
from app.models.domain import Domain

logger = logging.getLogger(__name__)


def _normalize_cert_dt(dt):
    """Normalize datetime to naive UTC for asyncpg compatibility."""
    from datetime import datetime, timezone
    if dt is None:
        return None
    if isinstance(dt, datetime) and dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class AcmeService:
    """Handles all ACME protocol interactions for certificate issuance."""

    # ── helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _load_or_create_account_key():
        """Load existing ACME account key or generate and persist a new one."""
        import josepy as jose
        from cryptography.hazmat.primitives.asymmetric import rsa
        from pathlib import Path

        account_key_path = Path(settings.ACME_ACCOUNT_KEY_PATH)
        account_key_path.parent.mkdir(parents=True, exist_ok=True)

        if account_key_path.exists():
            logger.info("Loading existing ACME account key")
            with open(account_key_path, "rb") as f:
                acc_key_crypto = serialization.load_pem_private_key(
                    f.read(), password=None, backend=default_backend()
                )
        else:
            logger.info("Generating new ACME account key")
            acc_key_crypto = rsa.generate_private_key(
                public_exponent=65537, key_size=2048, backend=default_backend()
            )
            with open(account_key_path, "wb") as f:
                f.write(acc_key_crypto.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                ))

        return jose.JWKRSA(key=acc_key_crypto), account_key_path

    @staticmethod
    def _init_acme_client(acc_key, account_key_path, email: str | None = None):
        """Create ACME client and register / retrieve account."""
        import acme.client
        import acme.messages
        from pathlib import Path

        net = acme.client.ClientNetwork(acc_key, user_agent="FlareCloud/1.0")
        directory = acme.messages.Directory.from_json(
            net.get(settings.ACME_DIRECTORY_URL).json()
        )
        client = acme.client.ClientV2(directory, net)

        acme_email = email or settings.ACME_EMAIL
        regr = None
        try:
            if Path(account_key_path).exists():
                try:
                    regr = client.new_account(
                        acme.messages.NewRegistration.from_data(
                            email=acme_email,
                            terms_of_service_agreed=True,
                            only_return_existing=True,
                        )
                    )
                except Exception as e:
                    if hasattr(e, "location"):
                        account_uri = getattr(e, "location", str(e).strip())
                        reg_body = acme.messages.Registration.from_data(email=acme_email)
                        regr = acme.messages.RegistrationResource(uri=account_uri, body=reg_body)
                        client.net.account = regr
                    elif "accountDoesNotExist" in str(e):
                        regr = client.new_account(
                            acme.messages.NewRegistration.from_data(
                                email=acme_email, terms_of_service_agreed=True
                            )
                        )
                    else:
                        raise
            else:
                try:
                    regr = client.new_account(
                        acme.messages.NewRegistration.from_data(
                            email=acme_email, terms_of_service_agreed=True
                        )
                    )
                except Exception as e:
                    if hasattr(e, "location"):
                        account_uri = getattr(e, "location", str(e).strip())
                        reg_body = acme.messages.Registration.from_data(email=acme_email)
                        regr = acme.messages.RegistrationResource(uri=account_uri, body=reg_body)
                        client.net.account = regr
                    else:
                        raise
        except Exception as exc:
            if regr is None:
                raise RuntimeError(f"Failed to register/retrieve ACME account: {exc}") from exc

        if client.net.account is None and regr is not None:
            client.net.account = regr

        return client, acc_key

    @staticmethod
    def _generate_csr(identifiers_list: list[str]):
        """Generate a private key and CSR for the given identifiers."""
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes

        pkey = rsa.generate_private_key(
            public_exponent=65537, key_size=2048, backend=default_backend()
        )
        san_dns_names = [x509.DNSName(name) for name in identifiers_list]
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(x509.Name([
                x509.NameAttribute(NameOID.COMMON_NAME, identifiers_list[0]),
            ]))
            .add_extension(x509.SubjectAlternativeName(san_dns_names), critical=False)
            .sign(pkey, hashes.SHA256(), default_backend())
        )
        return pkey, csr.public_bytes(serialization.Encoding.PEM)

    @staticmethod
    def _http01_token_str(http_challenge) -> str:
        """Return the HTTP-01 token as a base64url string (no padding)."""
        chall = getattr(http_challenge, "chall", http_challenge)
        try:
            token = chall.encode("token")
            if isinstance(token, bytes):
                return token.decode("ascii")
            return token
        except Exception:
            token_raw = getattr(chall, "token", None)
            if isinstance(token_raw, bytes):
                return base64.urlsafe_b64encode(token_raw).decode("ascii").rstrip("=")
            return str(token_raw)

    @staticmethod
    def _http01_validation_str(validation) -> str:
        """Convert validation (key-authorization) to string."""
        if isinstance(validation, bytes):
            return validation.decode("utf-8", errors="ignore")
        return str(validation)

    @staticmethod
    async def _validate_http01(client, acc_key, authz_resource) -> tuple[bool, str]:
        """Process a single HTTP-01 authorization. Returns (success, error_detail)."""
        import acme.messages
        import acme.challenges
        from app.core.redis import redis_client

        authz_url = authz_resource.uri if hasattr(authz_resource, "uri") else str(authz_resource)
        response = client._post_as_get(authz_url)
        authz = acme.messages.Authorization.from_json(response.json())

        http_challenge = None
        for chall in authz.challenges:
            if isinstance(chall.chall, acme.challenges.HTTP01):
                http_challenge = chall
                break

        if not http_challenge:
            return False, "No HTTP-01 challenge found"

        resp_obj, validation = http_challenge.response_and_validation(acc_key)
        token_str = AcmeService._http01_token_str(http_challenge)
        validation_str = AcmeService._http01_validation_str(validation)

        if not redis_client:
            return False, "Redis not available for ACME challenge storage"

        await redis_client.set(f"acme:challenge:{token_str}", validation_str, expire=3600)
        logger.info(f"Challenge stored for {authz.identifier.value}, token: {token_str[:30]}...")

        client.answer_challenge(http_challenge, resp_obj)

        for attempt in range(10):
            await asyncio.sleep(2)
            try:
                resp = client._post_as_get(authz_url)
                authz_status = acme.messages.Authorization.from_json(resp.json())
            except Exception as e:
                logger.warning(f"Status check attempt {attempt + 1} failed: {e}")
                continue

            if authz_status.status == acme.messages.STATUS_VALID:
                logger.info(f"Authorization validated for {authz.identifier.value}")
                return True, ""
            if authz_status.status == acme.messages.STATUS_INVALID:
                detail = ""
                for c in authz_status.challenges:
                    if hasattr(c, "error") and c.error:
                        detail = str(c.error)
                return False, f"Authorization INVALID for {authz.identifier.value}: {detail}"

        return False, f"Authorization timeout for {authz.identifier.value}"

    @staticmethod
    def _parse_fullchain_pem(fullchain_pem: str) -> dict:
        """Extract validity/issuer/subject from the leaf certificate of a fullchain PEM."""
        try:
            pem_start = "-----BEGIN CERTIFICATE-----"
            pem_end = "-----END CERTIFICATE-----"
            si = fullchain_pem.find(pem_start)
            ei = fullchain_pem.find(pem_end)
            if si == -1 or ei == -1:
                raise ValueError("Cannot find certificate boundaries in fullchain")
            first_cert_pem = fullchain_pem[si:ei + len(pem_end)] + "\n"
            leaf = x509.load_pem_x509_certificate(first_cert_pem.encode(), default_backend())
            return {
                "not_before": _normalize_cert_dt(
                    getattr(leaf, "not_valid_before_utc", leaf.not_valid_before)
                ),
                "not_after": _normalize_cert_dt(
                    getattr(leaf, "not_valid_after_utc", leaf.not_valid_after)
                ),
                "issuer": leaf.issuer.rfc4514_string(),
                "subject": leaf.subject.rfc4514_string(),
            }
        except Exception as e:
            logger.error(f"Failed to parse fullchain certificate: {e}")
            return {"not_before": None, "not_after": None, "issuer": "Unknown", "subject": "Unknown"}

    @staticmethod
    def _save_cert_result(cert, pkey, fullchain_pem: str, cert_info: dict):
        """Populate a Certificate model with the issued cert data."""
        from app.models.certificate import CertificateStatus
        from app.services.crypto_service import CryptoService

        raw_key = pkey.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        cert.cert_pem = fullchain_pem
        cert.key_pem = CryptoService.encrypt(raw_key)
        cert.status = CertificateStatus.ISSUED
        cert.not_before = cert_info["not_before"]
        cert.not_after = cert_info["not_after"]
        cert.issuer = cert_info["issuer"]
        cert.subject = cert_info["subject"]

    # ── public order methods ──────────────────────────────────────────

    @staticmethod
    async def process_acme_order(db: AsyncSession, domain_id: int):
        """Process ACME certificate order (multi-SAN, legacy path)."""
        from app.models.certificate import CertificateStatus
        from app.models.dns import DNSRecord

        domain_result = await db.execute(select(Domain).where(Domain.id == domain_id))
        domain = domain_result.scalar_one_or_none()
        if not domain:
            logger.error(f"Domain {domain_id} not found for ACME processing")
            return

        dns_records_result = await db.execute(
            select(DNSRecord).where(DNSRecord.domain_id == domain.id, DNSRecord.type == "A")
        )
        sans = {domain.name}
        for r in dns_records_result.scalars().all():
            if r.proxied:
                sans.add(domain.name if r.name == "@" else f"{r.name}.{domain.name}")
        identifiers_list = sorted(sans)
        logger.info(f"Requesting certificate for: {identifiers_list}")

        cert_result = await db.execute(
            select(Certificate)
            .where(Certificate.domain_id == domain_id, Certificate.status == CertificateStatus.PENDING)
            .order_by(Certificate.created_at.desc())
        )
        cert = cert_result.scalar_one_or_none()
        if not cert:
            logger.warning(f"No pending certificate found for domain {domain.name}")
            return

        try:
            acc_key, account_key_path = AcmeService._load_or_create_account_key()
            client, acc_key = AcmeService._init_acme_client(acc_key, account_key_path)
        except RuntimeError as e:
            logger.error(str(e))
            cert.status = CertificateStatus.FAILED
            await db.commit()
            return

        pkey, csr_pem = AcmeService._generate_csr(identifiers_list)
        order = client.new_order(csr_pem)

        for authz_resource in order.authorizations:
            ok, err = await AcmeService._validate_http01(client, acc_key, authz_resource)
            if not ok:
                logger.error(err)
                cert.status = CertificateStatus.FAILED
                await db.commit()
                return

        finalized_order = client.poll_and_finalize(order)
        cert_info = AcmeService._parse_fullchain_pem(finalized_order.fullchain_pem)
        AcmeService._save_cert_result(cert, pkey, finalized_order.fullchain_pem, cert_info)

        old_certs_result = await db.execute(
            select(Certificate).where(
                Certificate.domain_id == domain_id,
                Certificate.status == CertificateStatus.ISSUED,
                Certificate.id != cert.id,
            )
        )
        for old_cert in old_certs_result.scalars():
            old_cert.status = CertificateStatus.EXPIRED

        await db.commit()
        logger.info(f"Certificate issued successfully for {domain.name}")

    @staticmethod
    async def process_single_acme_order(
        db: AsyncSession,
        certificate_id: int,
        email: str = None
    ):
        """Process ACME order for a single certificate (one FQDN) with detailed logging."""
        from app.models.certificate import CertificateStatus
        from app.models.certificate_log import CertificateLog, CertificateLogLevel

        async def log(level: CertificateLogLevel, message: str, details: str = None):
            db.add(CertificateLog(
                certificate_id=certificate_id,
                level=level, message=message, details=details,
            ))
            await db.commit()

        cert_result = await db.execute(select(Certificate).where(Certificate.id == certificate_id))
        cert = cert_result.scalar_one_or_none()
        if not cert:
            logger.error(f"Certificate {certificate_id} not found")
            return

        domain_result = await db.execute(select(Domain).where(Domain.id == cert.domain_id))
        domain = domain_result.scalar_one_or_none()
        if not domain:
            cert.status = CertificateStatus.FAILED
            await log(CertificateLogLevel.ERROR, "Domain not found")
            return

        fqdn = cert.common_name
        await log(CertificateLogLevel.INFO, f"Starting certificate issuance for {fqdn}")

        try:
            acc_key, account_key_path = AcmeService._load_or_create_account_key()
        except Exception as e:
            logger.error(f"Account key error: {e}", exc_info=True)
            cert.status = CertificateStatus.FAILED
            await log(CertificateLogLevel.ERROR, f"Account key error: {e}")
            return

        await log(CertificateLogLevel.INFO, f"Connecting to ACME server: {settings.ACME_DIRECTORY_URL}")
        try:
            client, acc_key = AcmeService._init_acme_client(acc_key, account_key_path, email)
            await log(CertificateLogLevel.INFO, "ACME account ready")
        except RuntimeError as e:
            logger.error(str(e), exc_info=True)
            cert.status = CertificateStatus.FAILED
            await log(CertificateLogLevel.ERROR, f"Failed to register ACME account: {e}")
            return

        await log(CertificateLogLevel.INFO, "Generating certificate key and CSR")
        pkey, csr_pem = AcmeService._generate_csr([fqdn])

        await log(CertificateLogLevel.INFO, "Creating ACME order")
        try:
            order = client.new_order(csr_pem)
            await log(CertificateLogLevel.SUCCESS, "ACME order created successfully")
        except Exception as e:
            logger.error(f"Failed to create ACME order: {e}", exc_info=True)
            cert.status = CertificateStatus.FAILED
            await log(CertificateLogLevel.ERROR, f"Failed to create ACME order: {e}")
            return

        await log(CertificateLogLevel.INFO, f"Processing authorization for {fqdn}")
        for authz_resource in order.authorizations:
            ok, err = await AcmeService._validate_http01(client, acc_key, authz_resource)
            if ok:
                await log(CertificateLogLevel.SUCCESS, f"Authorization validated for {fqdn}")
            else:
                logger.error(err)
                cert.status = CertificateStatus.FAILED
                await log(CertificateLogLevel.ERROR, err)
                return

        await log(CertificateLogLevel.INFO, "Finalizing certificate order")
        try:
            finalized_order = client.poll_and_finalize(order)
        except Exception as e:
            logger.error(f"Failed to finalize order: {e}", exc_info=True)
            cert.status = CertificateStatus.FAILED
            await log(CertificateLogLevel.ERROR, f"Failed to finalize certificate order: {e}")
            return

        cert_info = AcmeService._parse_fullchain_pem(finalized_order.fullchain_pem)
        AcmeService._save_cert_result(cert, pkey, finalized_order.fullchain_pem, cert_info)

        old_certs_result = await db.execute(
            select(Certificate).where(
                Certificate.domain_id == cert.domain_id,
                Certificate.common_name == fqdn,
                Certificate.status == CertificateStatus.ISSUED,
                Certificate.id != cert.id,
            )
        )
        for old_cert in old_certs_result.scalars().all():
            old_cert.status = CertificateStatus.EXPIRED

        await log(
            CertificateLogLevel.SUCCESS,
            f"Certificate issued successfully for {fqdn}",
            f"Valid until: {cert_info['not_after']}",
        )
        logger.info(f"Certificate issued successfully for {fqdn}")

    @staticmethod
    async def request_acme_certificate(
        db: AsyncSession,
        domain_id: int,
        wildcard: bool = False
    ) -> Certificate:
        """Request Let's Encrypt certificate via ACME"""
        from app.models.certificate import CertificateStatus, CertificateType

        domain = await db.execute(select(Domain).where(Domain.id == domain_id))
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

        from app.tasks.certificate_tasks import issue_certificate
        issue_certificate.delay(domain_id)

        return certificate

    @staticmethod
    async def renew_certificate(
        db: AsyncSession,
        cert_id: int
    ) -> Optional[Certificate]:
        """Renew certificate by creating a new PENDING cert and triggering issuance."""
        from app.models.certificate import CertificateStatus, CertificateType
        from app.services.ssl_service import SSLService

        old_cert = await SSLService.get_certificate(db, cert_id)
        if not old_cert:
            return None

        if old_cert.type != CertificateType.ACME:
            raise ValueError("Only ACME certificates can be auto-renewed")

        new_cert = Certificate(
            domain_id=old_cert.domain_id,
            type=CertificateType.ACME,
            status=CertificateStatus.PENDING,
            common_name=old_cert.common_name,
            acme_challenge_type=old_cert.acme_challenge_type or "http-01",
        )
        db.add(new_cert)
        await db.commit()
        await db.refresh(new_cert)

        from app.tasks.certificate_tasks import issue_certificate
        issue_certificate.delay(old_cert.domain_id)

        return new_cert
