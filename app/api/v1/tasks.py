"""Task status API endpoints"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from celery.result import AsyncResult
from typing import Optional

from app.models.user import User
from app.core.security import get_current_superuser
from app.tasks import celery_app
from app.schemas.task import TaskStatusResponse

router = APIRouter()


# ==================== Analytics Task Triggers ====================

@router.post("/analytics/backfill")
async def trigger_analytics_backfill(
    days: int = Query(7, ge=1, le=30, description="Number of days to backfill"),
    current_user: User = Depends(get_current_superuser)
):
    """
    Trigger analytics backfill task (superuser only)
    
    This will aggregate historical data for the specified number of days.
    Useful after initial setup or data recovery.
    """
    from app.tasks.analytics_tasks import backfill_aggregations
    
    task = backfill_aggregations.delay(days)
    
    return {
        "message": f"Analytics backfill started for {days} days",
        "task_id": task.id,
        "status": "STARTED"
    }


@router.post("/analytics/aggregate-hourly")
async def trigger_hourly_aggregation(
    current_user: User = Depends(get_current_superuser)
):
    """
    Manually trigger hourly aggregation (superuser only)
    
    Aggregates raw logs from the previous hour into hourly stats.
    """
    from app.tasks.analytics_tasks import aggregate_hourly_stats
    
    task = aggregate_hourly_stats.delay()
    
    return {
        "message": "Hourly aggregation started",
        "task_id": task.id,
        "status": "STARTED"
    }


@router.post("/analytics/aggregate-daily")
async def trigger_daily_aggregation(
    current_user: User = Depends(get_current_superuser)
):
    """
    Manually trigger daily aggregation (superuser only)
    
    Aggregates hourly stats from yesterday into daily stats.
    Also aggregates geo, top paths, and error stats.
    """
    from app.tasks.analytics_tasks import aggregate_daily_stats
    
    task = aggregate_daily_stats.delay()
    
    return {
        "message": "Daily aggregation started",
        "task_id": task.id,
        "status": "STARTED"
    }


@router.post("/analytics/cleanup")
async def trigger_analytics_cleanup(
    current_user: User = Depends(get_current_superuser)
):
    """
    Manually trigger analytics data cleanup (superuser only)
    
    Removes old data based on retention policies:
    - Raw logs: 30 days
    - Hourly stats: 90 days
    - Daily stats: 365 days
    """
    from app.tasks.analytics_tasks import cleanup_old_analytics_data
    
    task = cleanup_old_analytics_data.delay()
    
    return {
        "message": "Analytics cleanup started",
        "task_id": task.id,
        "status": "STARTED"
    }


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    current_user: User = Depends(get_current_superuser)
):
    """
    Get status of an async task (superuser only)
    
    Returns task status and result when available.
    Status can be: PENDING, STARTED, PROGRESS, SUCCESS, FAILURE, REVOKED
    """
    result = AsyncResult(task_id, app=celery_app)
    
    response = TaskStatusResponse(
        task_id=task_id,
        status=result.status,
        progress=None,
        result=None,
        error=None
    )
    
    if result.status == 'PENDING':
        # Task not started yet or doesn't exist
        response.progress = "Waiting for task to start..."
        
    elif result.status == 'STARTED':
        response.progress = "Task started..."
        
    elif result.status == 'PROGRESS':
        # Task is running, get progress info
        if result.info:
            response.progress = result.info.get('progress', 'Processing...')
            
    elif result.status == 'SUCCESS':
        # Task completed successfully
        response.result = result.result
        
    elif result.status == 'FAILURE':
        # Task failed
        response.error = str(result.result) if result.result else "Unknown error"
        
    elif result.status == 'REVOKED':
        response.error = "Task was cancelled"
    
    return response


@router.delete("/{task_id}")
async def cancel_task(
    task_id: str,
    current_user: User = Depends(get_current_superuser)
):
    """
    Cancel/revoke a running task (superuser only)
    
    Note: This may not immediately stop the task if it's already executing.
    """
    result = AsyncResult(task_id, app=celery_app)
    
    if result.status in ('SUCCESS', 'FAILURE'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Task has already completed"
        )
    
    result.revoke(terminate=True)
    
    return {"message": "Task cancellation requested", "task_id": task_id}
