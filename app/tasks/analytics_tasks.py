"""Celery-задачи сводов аналитики и уборки.

Ошибка задачи теперь доходит до Celery как FAILURE. До 23.09.2026 обёртки
ловили исключение и возвращали {"status": "error"}, Celery показывал SUCCESS,
и почасовой свод падал каждый час месяцами, никому об этом не сообщая.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from celery import shared_task

from app.tasks.utils import create_task_db_session
from app.services import analytics_aggregation as agg

logger = logging.getLogger(__name__)


def _run(job, name: str):
    """Выполнить асинхронную работу со своей сессией БД и честным статусом."""
    async def _inner():
        engine, SessionLocal = create_task_db_session()
        try:
            async with SessionLocal() as db:
                return await job(db)
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(_inner())
    except Exception:
        logger.exception("%s: задача упала", name)
        raise
    logger.info("%s: %s", name, result)
    return {"status": "success", "result": result}


@shared_task(name="app.tasks.analytics.aggregate_hourly")
def aggregate_hourly_stats(hours: int = agg.RECENT_HOURS):
    """Пересчитать текущий и последние часы (каждые 5 минут)."""
    return _run(lambda db: agg.aggregate_recent_hours(db, hours), "aggregate_hourly")


@shared_task(name="app.tasks.analytics.aggregate_daily")
def aggregate_daily_stats():
    """Суточные своды за вчера: итоги, страны, топ страниц, ошибки.

    Перед этим досчитываем последние часы вчерашнего дня: задача идёт в 00:15,
    и последний час суток мог не успеть попасть в почасовой свод.
    """
    async def job(db):
        await agg.aggregate_recent_hours(db)
        yesterday = (datetime.utcnow() - timedelta(days=1)).date()
        return await agg.aggregate_day(db, yesterday)

    return _run(job, "aggregate_daily")


@shared_task(name="app.tasks.analytics.cleanup_old_data")
def cleanup_old_analytics_data():
    """Уборка по срокам хранения: сырые логи, часы, сутки."""
    return _run(agg.cleanup_old_data, "cleanup_old_data")


@shared_task(name="app.tasks.analytics.backfill_aggregations")
def backfill_aggregations(days: int = 7):
    """Пересчитать своды по сырым логам за последние ``days`` дней."""
    since = datetime.utcnow() - timedelta(days=days)
    return _run(lambda db: agg.backfill(db, since), "backfill_aggregations")
