"""Shared utilities for Celery tasks"""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings


def create_task_db_session():
    """
    Create a new database engine and session factory for use in Celery tasks.
    
    Each Celery task runs in its own process/thread with its own event loop
    (via asyncio.run()), so we need a fresh engine that's bound to the current
    event loop. Reusing the global engine from app.core.database causes
    "cannot perform operation: another operation is in progress" errors because
    asyncpg connections can only handle one operation at a time and the global
    pool is shared across concurrent tasks.
    """
    task_engine = create_async_engine(
        str(settings.DATABASE_URL),
        pool_size=5,
        max_overflow=10,
        echo=settings.DEBUG,
    )
    session_factory = async_sessionmaker(
        task_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    return task_engine, session_factory
