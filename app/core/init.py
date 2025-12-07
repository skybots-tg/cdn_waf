"""System initialization and setup utilities"""
import asyncio
import logging
from sqlalchemy import text
from app.core.database import async_session_maker, engine
from app.core.config import settings
from app.models import Base

logger = logging.getLogger(__name__)


async def create_tables():
    """Create all database tables"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created successfully")


async def check_database_connection():
    """Check database connection"""
    try:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
        logger.info("Database connection successful")
        return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False


async def init_system():
    """Initialize system on startup"""
    logger.info("Initializing CDN WAF system...")
    
    # Check database
    db_ok = await check_database_connection()
    if not db_ok:
        logger.error("Cannot start: Database connection failed")
        return False
    
    # Create tables if needed
    try:
        await create_tables()
    except Exception as e:
        logger.warning(f"Table creation warning (may already exist): {e}")
    
    logger.info("System initialized successfully")
    return True


if __name__ == "__main__":
    asyncio.run(init_system())
