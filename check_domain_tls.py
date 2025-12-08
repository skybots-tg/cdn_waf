#!/usr/bin/env python3
"""
Скрипт для проверки TLS настроек домена
"""
import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.domain import Domain
from app.models.certificate import Certificate, CertificateStatus

async def check_domain(domain_id: int):
    async with AsyncSessionLocal() as db:
        # Получаем домен
        result = await db.execute(select(Domain).where(Domain.id == domain_id))
        domain = result.scalar_one_or_none()
        
        if not domain:
            print(f"❌ Домен с ID {domain_id} не найден")
            return
        
        print(f"\n{'='*60}")
        print(f"ДОМЕН: {domain.name}")
        print(f"{'='*60}")
        print(f"ID: {domain.id}")
        print(f"Status: {domain.status}")
        print(f"Organization ID: {domain.organization_id}")
        
        # Получаем сертификат
        cert_result = await db.execute(
            select(Certificate).where(
                Certificate.domain_id == domain_id,
                Certificate.status == CertificateStatus.ISSUED
            ).order_by(Certificate.not_after.desc())
        )
        certificate = cert_result.scalar_one_or_none()
        
        print(f"\n{'='*60}")
        print(f"СЕРТИФИКАТ")
        print(f"{'='*60}")
        
        if certificate:
            print(f"✅ Сертификат найден")
            print(f"   ID: {certificate.id}")
            print(f"   Status: {certificate.status}")
            print(f"   Issuer: {certificate.issuer}")
            print(f"   Subject: {certificate.subject}")
            print(f"   Valid from: {certificate.not_before}")
            print(f"   Valid until: {certificate.not_after}")
            print(f"   Type: {certificate.type}")
            
            # Проверяем наличие файлов сертификата
            has_cert = bool(certificate.cert_pem and len(certificate.cert_pem) > 100)
            has_key = bool(certificate.key_pem and len(certificate.key_pem) > 100)
            
            print(f"\n   Certificate PEM: {'✅' if has_cert else '❌'} ({len(certificate.cert_pem or '')} bytes)")
            print(f"   Private Key PEM: {'✅' if has_key else '❌'} ({len(certificate.key_pem or '')} bytes)")
            print(f"   Chain PEM: {len(certificate.chain_pem or '')} bytes")
            
        else:
            print(f"❌ Активный сертификат не найден")
            
            # Проверяем все сертификаты для этого домена
            all_certs_result = await db.execute(
                select(Certificate).where(Certificate.domain_id == domain_id)
                .order_by(Certificate.created_at.desc())
            )
            all_certs = all_certs_result.scalars().all()
            
            if all_certs:
                print(f"\nНайдены другие сертификаты ({len(all_certs)}):")
                for cert in all_certs:
                    print(f"   - ID {cert.id}: status={cert.status}, created={cert.created_at}")
            else:
                print("\nСертификатов для этого домена вообще нет")
        
        # Проверяем настройки TLS (если есть в модели)
        print(f"\n{'='*60}")
        print(f"TLS НАСТРОЙКИ")
        print(f"{'='*60}")
        
        tls_mode = getattr(domain, 'tls_mode', None)
        force_https = getattr(domain, 'force_https', None)
        hsts_enabled = getattr(domain, 'hsts_enabled', None)
        
        if tls_mode is not None:
            print(f"TLS Mode: {tls_mode}")
        else:
            print(f"TLS Mode: не задан (нет поля в модели)")
            
        if force_https is not None:
            print(f"Force HTTPS: {force_https}")
        else:
            print(f"Force HTTPS: не задан (нет поля в модели)")
            
        if hsts_enabled is not None:
            print(f"HSTS Enabled: {hsts_enabled}")
        else:
            print(f"HSTS Enabled: не задан (нет поля в модели)")
        
        # Выводим итоговый статус
        print(f"\n{'='*60}")
        print(f"ИТОГО")
        print(f"{'='*60}")
        
        if certificate and certificate.status == CertificateStatus.ISSUED:
            print(f"✅ TLS должен быть включен (tls.enabled = True)")
            print(f"✅ Certificate ID: {certificate.id}")
        else:
            print(f"❌ TLS будет отключен (нет активного сертификата)")
        
        print(f"\n")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python check_domain_tls.py <domain_id>")
        print("Example: python check_domain_tls.py 2")
        sys.exit(1)
    
    domain_id = int(sys.argv[1])
    asyncio.run(check_domain(domain_id))

