"""System initialization and setup utilities"""
import asyncio
import logging
from sqlalchemy import text, select
from app.core.database import AsyncSessionLocal, engine
from app.core.config import settings
from app.models import Base
from app.models.user import User
from app.models.organization import Organization, OrganizationRole, OrganizationMember
from app.core.security import get_password_hash

logger = logging.getLogger(__name__)


async def create_tables():
    """Create all database tables"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created successfully")


async def seed_data():
    """Seed initial data"""
    try:
        async with AsyncSessionLocal() as session:
            # Check if default user exists
            result = await session.execute(select(User).filter(User.email == "admin@example.com"))
            user = result.scalars().first()
            
            if not user:
                logger.info("Creating default admin user...")
                user = User(
                    email="admin@example.com",
                    password_hash=get_password_hash("admin"),
                    full_name="Admin User",
                    is_active=True,
                    is_superuser=True
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)
                logger.info(f"Created user with ID {user.id}")
            
            # Check if default organization exists
            result = await session.execute(select(Organization).filter(Organization.id == 1))
            org = result.scalars().first()
            
            if not org:
                logger.info("Creating default organization...")
                org = Organization(
                    id=1,  # Force ID 1 as required by hardcoded values
                    name="Default Organization",
                    owner_id=user.id
                )
                session.add(org)
                await session.flush()
                
                # Add user as member
                member = OrganizationMember(
                    organization_id=org.id,
                    user_id=user.id,
                    role=OrganizationRole.OWNER
                )
                session.add(member)
                
                await session.commit()
                logger.info("Created default organization")
    except Exception as e:
        logger.error(f"Error seeding data: {e}")


async def check_database_connection():
    """Check database connection"""
    try:
        async with AsyncSessionLocal() as session:
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

    # Seed initial data
    await seed_data()
    
    logger.info("System initialized successfully")
    return True


if __name__ == "__main__":
    asyncio.run(init_system())
