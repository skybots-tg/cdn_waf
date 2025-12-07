import asyncio
import sys
from getpass import getpass

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
# Import all models to ensure relationships are resolved
from app.models import User, Organization
from app.core.security import get_password_hash


async def create_superuser():
    print("=== Create Superuser ===")
    
    email = input("Email: ").strip()
    if not email:
        print("Error: Email is required")
        return

    password = getpass("Password: ")
    if not password:
        print("Error: Password is required")
        return
        
    password_confirm = getpass("Confirm Password: ")
    if password != password_confirm:
        print("Error: Passwords do not match")
        return

    full_name = input("Full Name (optional): ").strip()

    async with AsyncSessionLocal() as session:
        # Check if user exists
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if user:
            print(f"User {email} already exists.")
            confirm = input("Do you want to promote this user to superuser? (y/n): ").lower()
            if confirm == 'y':
                user.is_superuser = True
                user.is_active = True
                session.add(user)
                await session.commit()
                print(f"Successfully promoted {email} to superuser!")
            else:
                print("Operation cancelled.")
        else:
            # Create new superuser
            new_user = User(
                email=email,
                password_hash=get_password_hash(password),
                full_name=full_name,
                is_active=True,
                is_superuser=True
            )
            session.add(new_user)
            await session.commit()
            print(f"Successfully created superuser {email}!")


if __name__ == "__main__":
    try:
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(create_superuser())
    except KeyboardInterrupt:
        print("\nOperation cancelled.")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
