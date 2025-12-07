"""System initialization and setup utilities"""
import asyncio
import logging
from sqlalchemy import text, select
from app.core.database import AsyncSessionLocal, engine, Base
import app.models # Register all models
from app.core.config import settings
# from app.models import Base
from app.models.user import User
from app.models.organization import Organization, OrganizationRole, OrganizationMember
from app.core.security import get_password_hash

logger = logging.getLogger(__name__)


async def create_tables():
    """Create all database tables"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created successfully")


async def migrate_schema():
    """Run manual schema migrations"""
    try:
        async with AsyncSessionLocal() as session:
            # 1. Check/Add ssh_host and related fields (older migration)
            result = await session.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='edge_nodes' AND column_name='ssh_host'"
            ))
            
            if not result.scalar():
                logger.info("Migrating edge_nodes table schema (ssh fields)...")
                await session.execute(text("ALTER TABLE edge_nodes ADD COLUMN IF NOT EXISTS ssh_host VARCHAR(255)"))
                await session.execute(text("ALTER TABLE edge_nodes ADD COLUMN IF NOT EXISTS ssh_port INTEGER DEFAULT 22"))
                await session.execute(text("ALTER TABLE edge_nodes ADD COLUMN IF NOT EXISTS ssh_user VARCHAR(255)"))
                await session.execute(text("ALTER TABLE edge_nodes ADD COLUMN IF NOT EXISTS ssh_key TEXT"))
                await session.commit()
            
            # 2. Check/Add ssh_password (new migration)
            result_pwd = await session.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='edge_nodes' AND column_name='ssh_password'"
            ))
            
            if not result_pwd.scalar():
                logger.info("Adding ssh_password column to edge_nodes...")
                await session.execute(text("ALTER TABLE edge_nodes ADD COLUMN IF NOT EXISTS ssh_password VARCHAR(255)"))
                await session.commit()

            # 3. Check/Add protocol to origins
            result_proto = await session.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='origins' AND column_name='protocol'"
            ))
            
            if not result_proto.scalar():
                logger.info("Adding protocol column to origins...")
                await session.execute(text("ALTER TABLE origins ADD COLUMN IF NOT EXISTS protocol VARCHAR(10) DEFAULT 'https' NOT NULL"))
                await session.commit()
                
    except Exception as e:
        logger.error(f"Schema migration error: {e}")


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
    logger.info("Initializing FlareCloud system...")
    
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

    # Run manual migrations
    await migrate_schema()

    # Seed initial data
    await seed_data()
    
    logger.info("System initialized successfully")
    return True


if __name__ == "__main__":
    asyncio.run(init_system())
