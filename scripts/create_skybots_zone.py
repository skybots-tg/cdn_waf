import asyncio
import os
import sys
import secrets
from datetime import datetime

# Add project root to path
sys.path.append(os.getcwd())

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.models.organization import Organization, OrganizationMember, OrganizationRole
from app.models.domain import Domain, DomainStatus, DomainTLSSettings
from app.models.dns import DNSRecord
from app.models.edge_node import EdgeNode

async def main():
    print("Starting zone creation/update for skybots.ru...")
    async with AsyncSessionLocal() as db:
        # 1. Find or Create User
        result = await db.execute(select(User))
        user = result.scalars().first()
        if not user:
            print("No users found. Creating default admin user...")
            user = User(
                email="admin@skybots.ru",
                hashed_password="hashed_password_placeholder",
                is_active=True,
                is_superuser=True
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            print(f"Created user: {user.email}")
        else:
            print(f"Using existing user: {user.email}")

        # 2. Find or Create Organization
        result = await db.execute(select(Organization).where(Organization.owner_id == user.id))
        org = result.scalars().first()
        if not org:
            print("Creating default organization...")
            org = Organization(
                name="Default Org",
                owner_id=user.id
            )
            db.add(org)
            await db.commit()
            await db.refresh(org)
            
            # Add member
            member = OrganizationMember(
                organization_id=org.id,
                user_id=user.id,
                role=OrganizationRole.OWNER
            )
            db.add(member)
            await db.commit()
            print(f"Created organization: {org.name}")
        else:
            print(f"Using existing organization: {org.name}")

        # 3. Find or Create Domain
        domain_name = "skybots.ru"
        result = await db.execute(select(Domain).where(Domain.name == domain_name))
        domain = result.scalar_one_or_none()
        
        if not domain:
            print(f"Creating domain {domain_name}...")
            domain = Domain(
                organization_id=org.id,
                name=domain_name,
                status=DomainStatus.ACTIVE, # FORCE ACTIVE
                verification_token=secrets.token_urlsafe(32),
                ns_verified=True,
                ns_verified_at=datetime.utcnow()
            )
            db.add(domain)
            await db.commit()
            await db.refresh(domain)
            
            # Create TLS settings
            tls = DomainTLSSettings(domain_id=domain.id)
            db.add(tls)
            await db.commit()
            print("Domain created.")
        else:
            print(f"Domain exists. Current status: {domain.status}")
            print("Updating status to ACTIVE and marking NS as verified...")
            domain.status = DomainStatus.ACTIVE
            domain.ns_verified = True
            if not domain.ns_verified_at:
                domain.ns_verified_at = datetime.utcnow()
            await db.commit()
            await db.refresh(domain)
            print("Domain updated to ACTIVE.")

        # 4. Create iherbcache Record
        record_name = "iherbcache"
        result = await db.execute(select(DNSRecord).where(
            DNSRecord.domain_id == domain.id,
            DNSRecord.name == record_name,
            DNSRecord.type == "A"
        ))
        record = result.scalar_one_or_none()
        
        # Check for edge nodes to decide on content
        from app.models.edge_node import EdgeNode
        edge_nodes = (await db.execute(select(EdgeNode).where(EdgeNode.status == "online"))).scalars().all()
        fallback_ip = edge_nodes[0].ip_address if edge_nodes else "127.0.0.1"
        
        if not record:
            print(f"Creating A record for {record_name}...")
            # We set proxied=True so it returns Edge Node IPs automatically
            # Content is just a placeholder origin if proxied
            record = DNSRecord(
                domain_id=domain.id,
                type="A",
                name=record_name,
                content=fallback_ip, # Use a real IP if available as fallback
                proxied=True,
                ttl=300
            )
            db.add(record)
            await db.commit()
            print(f"Record created (Proxied). Fallback IP: {fallback_ip}")
        else:
            print("Record iherbcache exists.")
            
        print("\nSUCCESS! Zone skybots.ru is ready in the database.")
        print("Please ensure you run the sync task or wait for auto-sync to push this to DNS nodes.")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())

