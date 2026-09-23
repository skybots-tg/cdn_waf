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
        "app.tasks.analytics_tasks",
        "app.tasks.health_tasks",
        "app.tasks.edge_health_tasks",
        "app.tasks.notification_tasks",
    ]
)

# Removed task_routes - all tasks will use default queue
# celery_app.conf.task_routes = {
#     "app.tasks.certificate.*": {"queue": "certificates"},
#     "app.tasks.dns.*": {"queue": "dns"},
#     "app.tasks.edge.*": {"queue": "edge"},
# }

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_soft_time_limit=120,
    task_time_limit=180,
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
    "check-pending-certificates-every-5-min": {
        "task": "app.tasks.certificate.check_pending_certificates",
        "schedule": crontab(minute="*/5"),
    },
    "check-expiring-certificates-every-hour": {
        "task": "app.tasks.certificate.check_expiring_certificates",
        "schedule": crontab(minute=0),  # Every hour at :00
    },
    # Primary health check with alerting and failsafe (every minute)
    "check-origins-health-every-1-min": {
        "task": "app.tasks.health.check_origins_health",
        "schedule": 60.0,
    },
    # Edge node availability check (HTTP + stale heartbeat)
    "check-edge-nodes-every-2-min": {
        "task": "app.tasks.health.check_edge_nodes_health",
        "schedule": crontab(minute="*/2"),
    },
    # Режим разработки домена истёк — ноды должны снова кэшировать.
    "sync-dev-mode-every-1-min": {
        "task": "app.tasks.edge.sync_dev_mode",
        "schedule": 60.0,
    },
    # DNS node availability check (HTTP)
    "check-dns-nodes-health-every-3-min": {
        "task": "app.tasks.health.check_dns_nodes_health",
        "schedule": crontab(minute="*/3"),
    },
    # Analytics tasks
    # Каждые 5 минут пересчитываем текущий и последние часы: экраны берут
    # прошедшие часы из свода, и раз в час свод отставал на час целиком.
    "aggregate-hourly-stats": {
        "task": "app.tasks.analytics.aggregate_hourly",
        "schedule": crontab(minute="*/5"),
    },
    "aggregate-daily-stats": {
        "task": "app.tasks.analytics.aggregate_daily",
        "schedule": crontab(hour=0, minute=15),  # Daily at 00:15 UTC
    },
    # Уведомления (вкладка «Notifications» в настройках). Время — UTC, 06:00 = 09:00 МСК.
    "notify-ssl-expiry-daily": {
        "task": "app.tasks.notify.ssl_expiry",
        "schedule": crontab(hour=6, minute=0),
    },
    "notify-security-spikes-hourly": {
        "task": "app.tasks.notify.security_spikes",
        "schedule": crontab(minute=7),  # после пересчёта свода за прошедший час
    },
    "notify-usage-hourly": {
        "task": "app.tasks.notify.usage",
        "schedule": crontab(minute=12),
    },
    "notify-weekly-report": {
        "task": "app.tasks.notify.weekly_report",
        "schedule": crontab(day_of_week=1, hour=6, minute=5),
    },
    "cleanup-old-analytics-data": {
        "task": "app.tasks.analytics.cleanup_old_data",
        "schedule": crontab(hour=3, minute=0),  # Daily at 03:00 UTC (low traffic time)
    },
}
