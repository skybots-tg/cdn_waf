"""Task schemas for async operations"""
from typing import Optional, Any, Dict
from pydantic import BaseModel, Field


class TaskStartResponse(BaseModel):
    """Response when starting an async task"""
    task_id: str = Field(..., description="Celery task ID")
    status: str = Field(default="PENDING", description="Initial task status")
    message: str = Field(default="Task started", description="Human-readable message")


class TaskStatusResponse(BaseModel):
    """Response for task status check"""
    task_id: str = Field(..., description="Celery task ID")
    status: str = Field(..., description="Task status: PENDING, STARTED, PROGRESS, SUCCESS, FAILURE, REVOKED")
    progress: Optional[str] = Field(None, description="Current progress message")
    result: Optional[Dict[str, Any]] = Field(None, description="Task result when completed")
    error: Optional[str] = Field(None, description="Error message if failed")


class ComponentTaskRequest(BaseModel):
    """Request to start a component task"""
    component: str = Field(..., description="Component name: nginx, redis, certbot, python, agent, system")
    action: str = Field(..., description="Action: start, stop, restart, reload, status, install, update")
    params: Optional[Dict[str, Any]] = Field(None, description="Additional parameters")
