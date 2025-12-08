"""Celery configuration"""
from celery import Celery
from celery.schedules import crontab
from app.core.config import settings

celery_app = Celery(
    "cdn_waf",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.certificate_tasks",
        "app.tasks.dns_tasks",
        "app.tasks.edge_tasks",
    ]
)

celery_app.conf.task_routes = {
    "app.tasks.certificate.*": {"queue": "certificates"},
    "app.tasks.dns.*": {"queue": "dns"},
    "app.tasks.edge.*": {"queue": "edge"},
}

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# Periodic tasks
celery_app.conf.beat_schedule = {
    "check-dns-health-every-5-min": {
        "task": "app.tasks.dns.check_dns_health",
        "schedule": crontab(minute="*/5"),
    },
    "verify-pending-domains-every-2-min": {
        "task": "app.tasks.dns.verify_pending_domains",
        "schedule": crontab(minute="*/2"),
    },
    "sync-dns-nodes-every-10-min": {
        "task": "app.tasks.dns.sync_dns_nodes",
        "schedule": crontab(minute="*/10"),
    },
}
