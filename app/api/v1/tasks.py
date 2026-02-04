"""Task status API endpoints"""
from fastapi import APIRouter, Depends, HTTPException, status
from celery.result import AsyncResult

from app.models.user import User
from app.core.security import get_current_superuser
from app.tasks import celery_app
from app.schemas.task import TaskStatusResponse

router = APIRouter()


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
