"""Celery configuration"""
from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "cdn_waf",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
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

