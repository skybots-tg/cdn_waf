"""Certificate management tasks"""
import asyncio
import logging
from celery import shared_task
from sqlalchemy import select
from datetime import datetime, timedelta
from app.tasks import celery_app
from app.core.database import AsyncSessionLocal
from app.services.ssl_service import SSLService

logger = logging.getLogger(__name__)

@celery_app.task(name="app.tasks.certificate.issue_certificate")
def issue_certificate(domain_id: int):
    """Issue SSL certificate for domain using ACME"""
    logger.info(f"Starting certificate issuance for domain_id={domain_id}")
    
    async def _issue():
        # Ensure Redis is connected for this task
        from app.core.redis import redis_client
        await redis_client.connect()
        
        async with AsyncSessionLocal() as db:
            try:
                await SSLService.process_acme_order(db, domain_id)
            except Exception as e:
                logger.error(f"Failed to issue certificate for domain {domain_id}: {e}", exc_info=True)
                # Ideally mark certificate/order as failed in DB
            finally:
                await redis_client.disconnect()

    asyncio.run(_issue())
    
    return {"status": "processed", "domain_id": domain_id}


@celery_app.task(name="app.tasks.certificate.renew_certificate")
def renew_certificate(certificate_id: int, force: bool = False):
    """
    Renew SSL certificate
    
    Args:
        certificate_id: ID of the certificate to renew
        force: Force renewal even if not expiring soon
    """
    logger.info(f"Starting certificate renewal for certificate_id={certificate_id}, force={force}")
    
    async def _renew():
        from app.core.redis import redis_client
        await redis_client.connect()
        
        async with AsyncSessionLocal() as db:
            try:
                from app.models.certificate import Certificate, CertificateStatus, CertificateType
                from app.models.certificate_log import CertificateLog, CertificateLogLevel
                
                # Get the certificate
                cert_result = await db.execute(
                    select(Certificate).where(Certificate.id == certificate_id)
                )
                cert = cert_result.scalar_one_or_none()
                
                if not cert:
                    logger.error(f"Certificate {certificate_id} not found")
                    return {"status": "error", "error": "Certificate not found"}
                
                # Check if it's an ACME certificate
                if cert.type != CertificateType.ACME:
                    logger.warning(f"Certificate {certificate_id} is not ACME type, cannot auto-renew")
                    return {"status": "error", "error": "Only ACME certificates can be auto-renewed"}
                
                # Check if renewal is needed (unless forced)
                if not force and cert.not_after:
                    days_until_expiry = (cert.not_after - datetime.utcnow()).days
                    if days_until_expiry > cert.renew_before_days:
                        logger.info(f"Certificate {certificate_id} not yet due for renewal ({days_until_expiry} days remaining)")
                        return {"status": "skipped", "reason": "Not yet due for renewal"}
                
                # Create a new pending certificate for renewal
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
                
                # Add log entry
                log_entry = CertificateLog(
                    certificate_id=new_cert.id,
                    level=CertificateLogLevel.INFO,
                    message=f"Certificate renewal started for {cert.common_name}",
                    details=f'{{"old_certificate_id": {cert.id}, "force": {str(force).lower()}}}'
                )
                db.add(log_entry)
                await db.commit()
                
                # Process the ACME order
                await SSLService.process_single_acme_order(db, new_cert.id)
                
                # Refresh to get updated status
                await db.refresh(new_cert)
                
                # If new certificate was issued successfully, mark old one as expired
                if new_cert.status == CertificateStatus.ISSUED:
                    cert.status = CertificateStatus.EXPIRED
                    new_cert.last_renewed_at = datetime.utcnow()
                    await db.commit()
                    
                    logger.info(f"Certificate {certificate_id} renewed successfully, new cert id={new_cert.id}")
                    return {"status": "success", "old_certificate_id": certificate_id, "new_certificate_id": new_cert.id}
                else:
                    logger.error(f"Certificate renewal failed for {certificate_id}, new cert status: {new_cert.status}")
                    return {"status": "failed", "certificate_id": certificate_id, "new_certificate_id": new_cert.id}
                    
            except Exception as e:
                logger.error(f"Failed to renew certificate {certificate_id}: {e}", exc_info=True)
                return {"status": "error", "error": str(e)}
            finally:
                await redis_client.disconnect()

    return asyncio.run(_renew())


@celery_app.task(name="app.tasks.certificate.check_expiring_certificates")
def check_expiring_certificates():
    """Check for certificates expiring soon and trigger renewal for auto-renew enabled ones"""
    logger.info("Checking expiring certificates")
    
    async def _check():
        from app.core.redis import redis_client
        await redis_client.connect()
        
        async with AsyncSessionLocal() as db:
            try:
                from app.models.certificate import Certificate, CertificateStatus, CertificateType
                from app.models.certificate_log import CertificateLog, CertificateLogLevel
                
                # Find all ACME certificates that are:
                # - Status: ISSUED
                # - auto_renew: True
                # - not_after: within renew_before_days from now
                now = datetime.utcnow()
                
                # Get all issued ACME certificates with auto_renew enabled
                result = await db.execute(
                    select(Certificate).where(
                        Certificate.status == CertificateStatus.ISSUED,
                        Certificate.type == CertificateType.ACME,
                        Certificate.auto_renew == True
                    )
                )
                certificates = result.scalars().all()
                
                renewed_count = 0
                skipped_count = 0
                error_count = 0
                
                for cert in certificates:
                    if not cert.not_after:
                        logger.warning(f"Certificate {cert.id} has no expiry date, skipping")
                        skipped_count += 1
                        continue
                    
                    days_until_expiry = (cert.not_after - now).days
                    
                    # Check if certificate needs renewal
                    if days_until_expiry <= cert.renew_before_days:
                        logger.info(f"Certificate {cert.id} ({cert.common_name}) expires in {days_until_expiry} days, triggering renewal")
                        
                        # Check if there's already a pending renewal
                        pending_result = await db.execute(
                            select(Certificate).where(
                                Certificate.domain_id == cert.domain_id,
                                Certificate.common_name == cert.common_name,
                                Certificate.status == CertificateStatus.PENDING
                            )
                        )
                        if pending_result.scalar_one_or_none():
                            logger.info(f"Certificate {cert.id} already has a pending renewal, skipping")
                            skipped_count += 1
                            continue
                        
                        # Trigger renewal task
                        renew_certificate.delay(cert.id)
                        renewed_count += 1
                    else:
                        logger.debug(f"Certificate {cert.id} ({cert.common_name}) expires in {days_until_expiry} days, no renewal needed")
                        skipped_count += 1
                
                logger.info(f"Expiring certificates check complete: {renewed_count} renewals triggered, {skipped_count} skipped, {error_count} errors")
                return {
                    "status": "success", 
                    "checked": len(certificates),
                    "renewed": renewed_count,
                    "skipped": skipped_count,
                    "errors": error_count
                }
                
            except Exception as e:
                logger.error(f"Failed to check expiring certificates: {e}", exc_info=True)
                return {"status": "error", "error": str(e)}
            finally:
                await redis_client.disconnect()
    
    return asyncio.run(_check())


@celery_app.task(name="app.tasks.certificate.check_pending_certificates")
def check_pending_certificates():
    """Check for certificates stuck in pending status and mark them as failed"""
    logger.info("Checking pending certificates")
    
    async def _check():
        from app.core.redis import redis_client
        await redis_client.connect()
        
        async with AsyncSessionLocal() as db:
            try:
                from app.models.certificate import Certificate, CertificateStatus
                from app.models.certificate_log import CertificateLog, CertificateLogLevel
                from datetime import datetime, timedelta
                
                # Find certificates that have been pending for more than 10 minutes
                # Use naive datetime since database stores TIMESTAMP WITHOUT TIME ZONE
                threshold_time = datetime.utcnow() - timedelta(minutes=10)
                
                result = await db.execute(
                    select(Certificate).where(
                        Certificate.status == CertificateStatus.PENDING,
                        Certificate.created_at < threshold_time
                    )
                )
                pending_certs = result.scalars().all()
                
                failed_count = 0
                for cert in pending_certs:
                    logger.warning(f"Certificate {cert.id} ({cert.common_name}) stuck in PENDING status, marking as FAILED")
                    cert.status = CertificateStatus.FAILED
                    
                    # Add log entry
                    log_entry = CertificateLog(
                        certificate_id=cert.id,
                        level=CertificateLogLevel.ERROR,
                        message="Certificate issuance failed due to timeout",
                        details="Certificate was stuck in PENDING status for more than 10 minutes"
                    )
                    db.add(log_entry)
                    failed_count += 1
                
                await db.commit()
                logger.info(f"Checked pending certificates: {len(pending_certs)} found, {failed_count} marked as failed")
                return {"status": "success", "checked": len(pending_certs), "failed": failed_count}
                
            except Exception as e:
                logger.error(f"Failed to check pending certificates: {e}", exc_info=True)
                return {"status": "error", "error": str(e)}
            finally:
                await redis_client.disconnect()
    
    return asyncio.run(_check())


@celery_app.task(name="app.tasks.certificate.issue_single_certificate")
def issue_single_certificate(certificate_id: int, email: str = None):
    """Issue SSL certificate for a specific subdomain using ACME"""
    logger.info(f"Starting single certificate issuance for certificate_id={certificate_id}")
    
    async def _issue():
        # Ensure Redis is connected for this task
        from app.core.redis import redis_client
        await redis_client.connect()
        
        async with AsyncSessionLocal() as db:
            try:
                await SSLService.process_single_acme_order(db, certificate_id, email)
            except Exception as e:
                logger.error(f"Failed to issue certificate {certificate_id}: {e}", exc_info=True)
                # Mark certificate as failed
                from app.models.certificate import Certificate, CertificateStatus
                from app.models.certificate_log import CertificateLog, CertificateLogLevel
                
                cert_result = await db.execute(
                    select(Certificate).where(Certificate.id == certificate_id)
                )
                cert = cert_result.scalar_one_or_none()
                if cert:
                    cert.status = CertificateStatus.FAILED
                    
                    log_entry = CertificateLog(
                        certificate_id=certificate_id,
                        level=CertificateLogLevel.ERROR,
                        message=f"Certificate issuance failed: {str(e)}",
                        details=str(e)
                    )
                    db.add(log_entry)
                    await db.commit()
            finally:
                await redis_client.disconnect()

    asyncio.run(_issue())
    
    return {"status": "processed", "certificate_id": certificate_id}