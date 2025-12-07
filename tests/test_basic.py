"""
Simple test script to verify basic functionality
"""
import asyncio
from app.core.config import settings


async def test_config():
    """Test configuration loading"""
    print("Testing configuration...")
    print(f"App Name: {settings.APP_NAME}")
    print(f"Debug: {settings.DEBUG}")
    print(f"Database URL: {str(settings.DATABASE_URL)[:50]}...")
    print("✓ Configuration loaded successfully")


async def test_database():
    """Test database connection"""
    print("\nTesting database connection...")
    try:
        from app.core.database import engine
        async with engine.begin() as conn:
            result = await conn.execute("SELECT 1")
            assert result.scalar() == 1
        print("✓ Database connection successful")
    except Exception as e:
        print(f"✗ Database connection failed: {e}")


async def test_redis():
    """Test Redis connection"""
    print("\nTesting Redis connection...")
    try:
        from app.core.redis import redis_client
        await redis_client.connect()
        await redis_client.set("test_key", "test_value", expire=10)
        value = await redis_client.get("test_key")
        assert value == "test_value"
        await redis_client.delete("test_key")
        await redis_client.disconnect()
        print("✓ Redis connection successful")
    except Exception as e:
        print(f"✗ Redis connection failed: {e}")


async def main():
    """Run all tests"""
    print("=" * 50)
    print("CDN WAF - Basic Functionality Test")
    print("=" * 50)
    
    await test_config()
    # Uncomment when database is ready:
    # await test_database()
    # await test_redis()
    
    print("\n" + "=" * 50)
    print("All tests completed!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())


