#!/usr/bin/env python3
"""
Fix redirect loop by disabling force_https until certificate is ready
Usage: python fix_redirect_loop.py <domain_name>
"""
import sys
import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.domain import Domain, DomainTLSSettings
from app.models.certificate import Certificate, CertificateStatus

async def fix_redirect_loop(domain_name: str):
    """Disable force_https for domain to fix redirect loop"""
    async with AsyncSessionLocal() as db:
        # Find domain
        result = await db.execute(
            select(Domain).where(Domain.name == domain_name)
        )
        domain = result.scalar_one_or_none()
        
        if not domain:
            print(f"❌ Domain '{domain_name}' not found")
            return
        
        print(f"✓ Found domain: {domain.name} (ID: {domain.id})")
        
        # Check certificate status
        cert_result = await db.execute(
            select(Certificate)
            .where(
                Certificate.domain_id == domain.id,
                Certificate.status == CertificateStatus.ISSUED
            )
            .order_by(Certificate.not_after.desc())
        )
        cert = cert_result.scalar_one_or_none()
        
        if cert:
            print(f"✓ Certificate: {cert.status.value}, expires: {cert.not_after}")
        else:
            print("⚠️  No active certificate found")
        
        # Get or create TLS settings
        tls_result = await db.execute(
            select(DomainTLSSettings).where(DomainTLSSettings.domain_id == domain.id)
        )
        tls_settings = tls_result.scalar_one_or_none()
        
        if not tls_settings:
            print("Creating default TLS settings...")
            from app.models.domain import TLSMode
            tls_settings = DomainTLSSettings(
                domain_id=domain.id,
                mode=TLSMode.FLEXIBLE,
                force_https=False,
                hsts_enabled=False,
                min_tls_version="1.2",
                auto_certificate=True
            )
            db.add(tls_settings)
        
        print(f"\nCurrent TLS settings:")
        print(f"  Mode: {tls_settings.mode.value}")
        print(f"  Force HTTPS: {tls_settings.force_https}")
        print(f"  HSTS Enabled: {tls_settings.hsts_enabled}")
        print(f"  Auto Certificate: {tls_settings.auto_certificate}")
        
        # Fix: disable force_https if no certificate or if explicitly requested
        if not cert or tls_settings.force_https:
            print(f"\n🔧 Fixing redirect loop:")
            if not cert:
                print("  - No certificate: disabling force_https")
                tls_settings.force_https = False
            else:
                print("  - Certificate exists: you can enable force_https safely")
                print("  - Keeping current settings")
            
            tls_settings.hsts_enabled = False  # Also disable HSTS
            
            await db.commit()
            print("✅ Settings updated!")
            print("\n💡 Recommended TLS settings:")
            if cert:
                print("  - Mode: flexible (edge HTTPS, origin HTTP)")
                print("  - Force HTTPS: true (redirect HTTP to HTTPS)")
                print("  - HSTS: false (enable only when stable)")
            else:
                print("  - Mode: flexible")
                print("  - Force HTTPS: false (until certificate is issued)")
                print("  - First get a certificate, then enable force_https")
        else:
            print("\n✅ Settings look good!")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python fix_redirect_loop.py <domain_name>")
        sys.exit(1)
    
    domain_name = sys.argv[1]
    asyncio.run(fix_redirect_loop(domain_name))

