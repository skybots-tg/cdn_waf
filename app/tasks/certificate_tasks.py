"""Certificate management tasks"""
import asyncio
import logging
from celery import shared_task
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
