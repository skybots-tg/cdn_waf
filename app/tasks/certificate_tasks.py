"""Certificate management tasks"""
import asyncio
import logging
from celery import shared_task
from sqlalchemy import select
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

    loop = asyncio.get_event_loop()
    loop.run_until_complete(_issue())
    
    return {"status": "processed", "domain_id": domain_id}


@celery_app.task(name="app.tasks.certificate.renew_certificate")
def renew_certificate(certificate_id: int):
    """Renew SSL certificate"""
    # TODO: Implement certificate renewal (similar to issuance but triggers check first)
    print(f"Renewing certificate {certificate_id}")
    return {"status": "success", "certificate_id": certificate_id}


@celery_app.task(name="app.tasks.certificate.check_expiring_certificates")
def check_expiring_certificates():
    """Check for certificates expiring soon and renew them"""
    # TODO: Implement certificate expiry checking
    print("Checking expiring certificates")
    return {"status": "success", "checked": 0}


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
    
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(_check())


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

    loop = asyncio.get_event_loop()
    loop.run_until_complete(_issue())
    
    return {"status": "processed", "certificate_id": certificate_id}