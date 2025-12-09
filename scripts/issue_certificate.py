#!/usr/bin/env python3
"""
Standalone script to issue SSL certificate with detailed logging
Usage: python scripts/issue_certificate.py medcard.ryabich.co
"""
import sys
import os
import asyncio
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Configure detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

async def issue_certificate(fqdn: str, email: str = None):
    """Issue SSL certificate for FQDN"""
    
    logger.info("=" * 80)
    logger.info(f"Starting certificate issuance for: {fqdn}")
    logger.info("=" * 80)
    
    # Import dependencies
    from app.core.database import AsyncSessionLocal
    from app.core.redis import redis_client
    from app.core.config import settings
    from app.models.domain import Domain
    from app.models.certificate import Certificate, CertificateStatus, CertificateType
    from app.models.certificate_log import CertificateLog, CertificateLogLevel
    from sqlalchemy import select
    import acme.client
    import acme.messages
    import acme.challenges
    import josepy as jose
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes
    import base64
    import time
    
    # Connect to Redis
    logger.info("\n[1/12] Connecting to Redis...")
    await redis_client.connect()
    logger.info(f"✓ Redis connected: {settings.REDIS_URL}")
    
    # Open database session
    logger.info("\n[2/12] Opening database connection...")
    async with AsyncSessionLocal() as db:
        try:
            # Parse domain from FQDN
            if '.' not in fqdn:
                raise ValueError(f"Invalid FQDN: {fqdn}")
            
            parts = fqdn.split('.')
            if len(parts) == 2:
                # Root domain
                domain_name = fqdn
                subdomain = "@"
            else:
                # Subdomain
                subdomain = parts[0]
                domain_name = '.'.join(parts[1:])
            
            logger.info(f"Domain: {domain_name}, Subdomain: {subdomain}")
            
            # Get domain from database
            logger.info("\n[3/12] Looking up domain in database...")
            result = await db.execute(
                select(Domain).where(Domain.name == domain_name)
            )
            domain = result.scalar_one_or_none()
            
            if not domain:
                raise ValueError(f"Domain {domain_name} not found in database")
            
            logger.info(f"✓ Domain found: ID={domain.id}, Name={domain.name}, Status={domain.status}")
            
            # Check for existing pending/issued certificates
            logger.info("\n[4/12] Checking for existing certificates...")
            existing = await db.execute(
                select(Certificate).where(
                    Certificate.domain_id == domain.id,
                    Certificate.common_name == fqdn
                )
            )
            existing_certs = existing.scalars().all()
            
            if existing_certs:
                logger.warning(f"Found {len(existing_certs)} existing certificate(s):")
                for cert in existing_certs:
                    logger.warning(f"  - ID={cert.id}, Status={cert.status}, Created={cert.created_at}")
                
                response = input("Delete existing certificates? [y/N]: ")
                if response.lower() == 'y':
                    # First delete certificate logs (due to NOT NULL constraint)
                    for cert in existing_certs:
                        await db.execute(
                            select(CertificateLog).where(CertificateLog.certificate_id == cert.id)
                        )
                        # Delete logs
                        logs_result = await db.execute(
                            select(CertificateLog).where(CertificateLog.certificate_id == cert.id)
                        )
                        logs = logs_result.scalars().all()
                        for log in logs:
                            await db.delete(log)
                        # Then delete certificate
                        await db.delete(cert)
                    
                    await db.commit()
                    logger.info("✓ Existing certificates and logs deleted")
                else:
                    logger.error("Cannot proceed with existing certificates")
                    return
            
            # Create new certificate record
            logger.info("\n[5/12] Creating certificate record...")
            cert = Certificate(
                domain_id=domain.id,
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
            logger.info(f"✓ Certificate created: ID={cert.id}")
            
            # Use provided email or default
            acme_email = email or settings.ACME_EMAIL
            logger.info(f"ACME email: {acme_email}")
            
            # Load or generate account key
            logger.info("\n[6/12] Setting up ACME account...")
            account_key_path = Path(settings.ACME_ACCOUNT_KEY_PATH)
            account_key_path.parent.mkdir(parents=True, exist_ok=True)
            
            if account_key_path.exists():
                logger.info(f"Loading existing account key from: {account_key_path}")
                with open(account_key_path, 'rb') as f:
                    acc_key_crypto = serialization.load_pem_private_key(
                        f.read(),
                        password=None,
                        backend=default_backend()
                    )
            else:
                logger.info("Generating new account key...")
                acc_key_crypto = rsa.generate_private_key(
                    public_exponent=65537,
                    key_size=2048,
                    backend=default_backend()
                )
                with open(account_key_path, 'wb') as f:
                    f.write(acc_key_crypto.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.PKCS8,
                        encryption=serialization.NoEncryption()
                    ))
                logger.info(f"✓ Account key saved to: {account_key_path}")
            
            acc_key = jose.JWKRSA(key=acc_key_crypto)
            
            # Initialize ACME client
            logger.info(f"\n[7/12] Connecting to ACME server: {settings.ACME_DIRECTORY_URL}")
            net = acme.client.ClientNetwork(acc_key, user_agent="FlareCloud-Debug/1.0")
            directory = acme.messages.Directory.from_json(
                net.get(settings.ACME_DIRECTORY_URL).json()
            )
            client = acme.client.ClientV2(directory, net)
            logger.info("✓ ACME client initialized")
            
            # Register or query account
            logger.info("Registering/querying ACME account...")
            import acme.errors
            regr = None
            
            try:
                # Try to query existing account first
                if account_key_path.exists():
                    logger.info("Querying existing ACME account...")
                    try:
                        regr = client.new_account(
                            acme.messages.NewRegistration.from_data(
                                email=acme_email,
                                terms_of_service_agreed=True,
                                only_return_existing=True
                            )
                        )
                        logger.info(f"✓ Using existing ACME account: {regr.uri}")
                    except acme.errors.ConflictError as conflict:
                        # Account exists but we got conflict - this is fine, we can continue
                        logger.info(f"✓ ACME account already registered (conflict resolved)")
                        # We can still use the client, just don't have regr object
                        regr = True  # Mark as successful
                    except Exception as account_error:
                        if "accountDoesNotExist" in str(account_error):
                            logger.info("Account doesn't exist, will create new one...")
                            regr = None
                        else:
                            raise
                
                # If no existing account, create new one
                if not regr:
                    logger.info("Creating new ACME account...")
                    regr = client.new_account(
                        acme.messages.NewRegistration.from_data(
                            email=acme_email,
                            terms_of_service_agreed=True
                        )
                    )
                    logger.info(f"✓ New ACME account created: {regr.uri}")
                    
            except Exception as e:
                logger.error(f"Failed to setup ACME account: {e}")
                raise
            
            # Generate certificate key and CSR
            logger.info("\n[8/12] Generating certificate key and CSR...")
            pkey = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            )
            
            san_dns_names = [x509.DNSName(fqdn)]
            csr_builder = x509.CertificateSigningRequestBuilder().subject_name(
                x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, fqdn)])
            )
            csr_builder = csr_builder.add_extension(
                x509.SubjectAlternativeName(san_dns_names),
                critical=False,
            )
            csr = csr_builder.sign(pkey, hashes.SHA256(), default_backend())
            csr_pem = csr.public_bytes(serialization.Encoding.PEM)
            logger.info("✓ CSR generated")
            
            # Create order
            logger.info("\n[9/12] Creating ACME order...")
            order = client.new_order(csr_pem)
            logger.info(f"✓ Order created: {order.uri}")
            logger.info(f"  Authorizations: {len(order.authorizations)}")
            
            # Process authorizations
            logger.info("\n[10/12] Processing HTTP-01 challenge...")
            for idx, authz_resource in enumerate(order.authorizations):
                authz_url = authz_resource.uri if hasattr(authz_resource, 'uri') else str(authz_resource)
                logger.info(f"\nAuthorization {idx + 1}/{len(order.authorizations)}: {authz_url}")
                
                response = client._post_as_get(authz_url)
                authz = acme.messages.Authorization.from_json(response.json())
                logger.info(f"  Domain: {authz.identifier.value}")
                logger.info(f"  Status: {authz.status}")
                
                # Find HTTP-01 challenge
                http_challenge = None
                for chall in authz.challenges:
                    logger.info(f"  Available challenge: {type(chall.chall).__name__}")
                    if isinstance(chall.chall, acme.challenges.HTTP01):
                        http_challenge = chall
                
                if not http_challenge:
                    raise ValueError("No HTTP-01 challenge found")
                
                # Generate response
                response_obj, validation = http_challenge.response_and_validation(acc_key)
                
                token_raw = http_challenge.chall.token
                if isinstance(token_raw, bytes):
                    token_str = base64.urlsafe_b64encode(token_raw).decode('ascii').rstrip('=')
                else:
                    token_str = str(token_raw)
                
                if isinstance(validation, bytes):
                    validation_str = validation.decode('utf-8')
                else:
                    validation_str = str(validation)
                
                challenge_url = f"http://{fqdn}/.well-known/acme-challenge/{token_str}"
                
                logger.info(f"\n  Challenge URL: {challenge_url}")
                logger.info(f"  Token: {token_str}")
                logger.info(f"  Validation (first 50 chars): {validation_str[:50]}...")
                
                # Store in Redis
                redis_key = f"acme:challenge:{token_str}"
                await redis_client.set(redis_key, validation_str, expire=3600)
                logger.info(f"  ✓ Challenge stored in Redis: {redis_key}")
                
                # Verify we can retrieve it
                test_val = await redis_client.get(redis_key)
                if test_val == validation_str:
                    logger.info("  ✓ Verified: Token can be retrieved from Redis")
                else:
                    logger.error(f"  ✗ ERROR: Token mismatch! Stored: {validation_str[:20]}..., Retrieved: {test_val[:20] if test_val else 'None'}...")
                
                # Test local endpoint
                logger.info("\n  Testing local ACME endpoint...")
                import httpx
                try:
                    async with httpx.AsyncClient() as http_client:
                        test_response = await http_client.get(
                            f"http://localhost:8000/.well-known/acme-challenge/{token_str}",
                            timeout=5.0
                        )
                        if test_response.status_code == 200:
                            logger.info(f"  ✓ Local endpoint responds: {test_response.text[:50]}...")
                            if test_response.text == validation_str:
                                logger.info("  ✓ Response matches expected validation!")
                            else:
                                logger.warning("  ⚠ Response doesn't match!")
                        else:
                            logger.error(f"  ✗ Local endpoint error: {test_response.status_code}")
                except Exception as e:
                    logger.error(f"  ✗ Failed to test local endpoint: {e}")
                
                # Test public endpoint
                logger.info(f"\n  Testing public ACME endpoint (http://{fqdn})...")
                try:
                    async with httpx.AsyncClient() as http_client:
                        test_response = await http_client.get(
                            challenge_url,
                            timeout=10.0,
                            follow_redirects=True
                        )
                        if test_response.status_code == 200:
                            logger.info(f"  ✓ Public endpoint responds: {test_response.text[:50]}...")
                            if test_response.text == validation_str:
                                logger.info("  ✓ PUBLIC ENDPOINT WORKS! Let's Encrypt should succeed!")
                            else:
                                logger.warning(f"  ⚠ Response mismatch!")
                                logger.warning(f"    Expected: {validation_str[:100]}")
                                logger.warning(f"    Got:      {test_response.text[:100]}")
                        else:
                            logger.error(f"  ✗ Public endpoint error: {test_response.status_code}")
                            logger.error(f"    Response: {test_response.text[:200]}")
                except Exception as e:
                    logger.error(f"  ✗ Failed to test public endpoint: {e}")
                    logger.error("    This means Let's Encrypt will also fail!")
                
                # Ask user if they want to continue
                logger.info("\n" + "=" * 80)
                response = input("Continue with ACME validation? [Y/n]: ")
                if response.lower() == 'n':
                    logger.info("Aborted by user")
                    cert.status = CertificateStatus.FAILED
                    await db.commit()
                    return
                
                # Answer challenge
                logger.info("\n[11/12] Triggering ACME validation...")
                client.answer_challenge(http_challenge, response_obj)
                logger.info("✓ Challenge answer sent to ACME server")
                
                # Poll for validation
                logger.info("\nWaiting for Let's Encrypt to validate...")
                for attempt in range(15):
                    await asyncio.sleep(2)
                    
                    response = client._post_as_get(authz_url)
                    authz_status = acme.messages.Authorization.from_json(response.json())
                    
                    logger.info(f"  Attempt {attempt + 1}/15: Status = {authz_status.status}")
                    
                    if authz_status.status == acme.messages.STATUS_VALID:
                        logger.info("  ✓✓✓ VALIDATION SUCCESSFUL! ✓✓✓")
                        break
                    elif authz_status.status == acme.messages.STATUS_INVALID:
                        logger.error("  ✗✗✗ VALIDATION FAILED! ✗✗✗")
                        
                        # Print detailed error
                        for chall in authz_status.challenges:
                            if hasattr(chall, 'error') and chall.error:
                                logger.error(f"  Error type: {chall.error.get('type', 'unknown')}")
                                logger.error(f"  Error detail: {chall.error.get('detail', 'no detail')}")
                                logger.error(f"  Full error: {chall.error}")
                        
                        cert.status = CertificateStatus.FAILED
                        await db.commit()
                        return
                    elif authz_status.status == acme.messages.STATUS_PENDING:
                        logger.info("  Still pending...")
                    else:
                        logger.warning(f"  Unknown status: {authz_status.status}")
                else:
                    logger.error("  ✗ Timeout waiting for validation")
                    cert.status = CertificateStatus.FAILED
                    await db.commit()
                    return
            
            # Finalize order
            logger.info("\n[12/12] Finalizing order and downloading certificate...")
            finalized_order = client.poll_and_finalize(order)
            fullchain_pem = finalized_order.fullchain_pem
            
            # Parse certificate
            pem_start = "-----BEGIN CERTIFICATE-----"
            pem_end = "-----END CERTIFICATE-----"
            start_idx = fullchain_pem.find(pem_start)
            end_idx = fullchain_pem.find(pem_end)
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
            
            # Save certificate
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
            
            logger.info("\n" + "=" * 80)
            logger.info("✓✓✓ CERTIFICATE ISSUED SUCCESSFULLY! ✓✓✓")
            logger.info("=" * 80)
            logger.info(f"Certificate ID: {cert.id}")
            logger.info(f"Common Name: {cert.common_name}")
            logger.info(f"Issuer: {cert.issuer}")
            logger.info(f"Valid from: {cert.not_before}")
            logger.info(f"Valid until: {cert.not_after}")
            logger.info(f"Certificate length: {len(cert.cert_pem)} bytes")
            logger.info(f"Key length: {len(cert.key_pem)} bytes")
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error("\n" + "=" * 80)
            logger.error(f"✗✗✗ ERROR: {e}")
            logger.error("=" * 80)
            import traceback
            traceback.print_exc()
            raise
        finally:
            await redis_client.disconnect()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/issue_certificate.py <fqdn> [email]")
        print("Example: python scripts/issue_certificate.py medcard.ryabich.co admin@example.com")
        sys.exit(1)
    
    fqdn = sys.argv[1]
    email = sys.argv[2] if len(sys.argv) > 2 else None
    
    asyncio.run(issue_certificate(fqdn, email))

