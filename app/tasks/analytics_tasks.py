"""Celery tasks for analytics aggregation and cleanup"""
import logging
from datetime import datetime, timedelta, date
from celery import shared_task

from app.core.database import AsyncSessionLocal
from app.services.analytics_service import AnalyticsService

logger = logging.getLogger(__name__)


@shared_task(name="app.tasks.analytics.aggregate_hourly")
def aggregate_hourly_stats():
    """
    Aggregate raw logs into hourly stats.
    Runs every hour, processes the previous hour.
    """
    import asyncio
    
    async def _run():
        async with AsyncSessionLocal() as db:
            try:
                # Aggregate previous hour
                records = await AnalyticsService.aggregate_hourly_stats(db)
                logger.info(f"Hourly aggregation completed: {records} records")
                return {"status": "success", "records": records}
            except Exception as e:
                logger.error(f"Hourly aggregation failed: {e}", exc_info=True)
                return {"status": "error", "error": str(e)}
    
    return asyncio.run(_run())


@shared_task(name="app.tasks.analytics.aggregate_daily")
def aggregate_daily_stats():
    """
    Aggregate hourly stats into daily stats.
    Runs once a day at 00:15, processes the previous day.
    """
    import asyncio
    
    async def _run():
        async with AsyncSessionLocal() as db:
            try:
                yesterday = (datetime.utcnow() - timedelta(days=1)).date()
                
                # Aggregate daily stats
                daily_records = await AnalyticsService.aggregate_daily_stats(db, yesterday)
                
                # Aggregate geo stats
                geo_records = await AnalyticsService.aggregate_geo_stats(db, yesterday)
                
                # Aggregate top paths
                paths_records = await AnalyticsService.aggregate_top_paths(db, yesterday)
                
                # Aggregate error stats
                error_records = await AnalyticsService.aggregate_error_stats(db, yesterday)
                
                total = daily_records + geo_records + paths_records + error_records
                logger.info(f"Daily aggregation completed: {total} total records")
                
                return {
                    "status": "success",
                    "daily_stats": daily_records,
                    "geo_stats": geo_records,
                    "top_paths": paths_records,
                    "error_stats": error_records,
                    "total": total
                }
            except Exception as e:
                logger.error(f"Daily aggregation failed: {e}", exc_info=True)
                return {"status": "error", "error": str(e)}
    
    return asyncio.run(_run())


@shared_task(name="app.tasks.analytics.cleanup_old_data")
def cleanup_old_analytics_data():
    """
    Clean up old analytics data based on retention policies.
    - Raw logs: 30 days
    - Hourly stats: 90 days  
    - Daily/Geo/Path stats: 365 days (but we store 6 months = 180 days of detailed data)
    
    Runs once a day at 03:00 to minimize impact.
    """
    import asyncio
    
    async def _run():
        async with AsyncSessionLocal() as db:
            try:
                deleted = await AnalyticsService.cleanup_old_data(db)
                
                total_deleted = sum(deleted.values())
                logger.info(f"Cleanup completed: {total_deleted} total records deleted")
                
                return {
                    "status": "success",
                    "deleted": deleted,
                    "total_deleted": total_deleted
                }
            except Exception as e:
                logger.error(f"Cleanup failed: {e}", exc_info=True)
                return {"status": "error", "error": str(e)}
    
    return asyncio.run(_run())


@shared_task(name="app.tasks.analytics.backfill_aggregations")
def backfill_aggregations(days: int = 7):
    """
    Backfill aggregations for the past N days.
    Useful when setting up analytics for the first time or after data issues.
    """
    import asyncio
    
    async def _run():
        async with AsyncSessionLocal() as db:
            try:
                results = {
                    "hourly": 0,
                    "daily": 0,
                    "geo": 0,
                    "paths": 0,
                    "errors": 0
                }
                
                now = datetime.utcnow()
                
                # Backfill hourly stats
                for hours_ago in range(1, days * 24 + 1):
                    target_hour = now - timedelta(hours=hours_ago)
                    target_hour = target_hour.replace(minute=0, second=0, microsecond=0)
                    
                    records = await AnalyticsService.aggregate_hourly_stats(db, target_hour)
                    results["hourly"] += records
                
                # Backfill daily stats
                for days_ago in range(1, days + 1):
                    target_date = (now - timedelta(days=days_ago)).date()
                    
                    results["daily"] += await AnalyticsService.aggregate_daily_stats(db, target_date)
                    results["geo"] += await AnalyticsService.aggregate_geo_stats(db, target_date)
                    results["paths"] += await AnalyticsService.aggregate_top_paths(db, target_date)
                    results["errors"] += await AnalyticsService.aggregate_error_stats(db, target_date)
                
                total = sum(results.values())
                logger.info(f"Backfill completed: {total} total records for {days} days")
                
                return {
                    "status": "success",
                    "days_processed": days,
                    "records": results,
                    "total": total
                }
            except Exception as e:
                logger.error(f"Backfill failed: {e}", exc_info=True)
                return {"status": "error", "error": str(e)}
    
    return asyncio.run(_run())
