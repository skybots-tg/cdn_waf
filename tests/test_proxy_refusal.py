"""
Что можно пускать через CDN: только адреса сайтов, как у Cloudflare.

До 23.09.2026 скан зоны при добавлении домена проксировал все A/AAAA/CNAME,
включая CNAME DKIM-ключей Proton у reshu.app: DNS отдавал на этом имени сразу
CNAME и адреса edge-нод, а подписи писем держались на поведении резолверов.
"""

import os
import secrets

import pytest

for _key, _value in {
    "SECRET_KEY": "test-secret",
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db",
    "REDIS_URL": "redis://localhost:6379/0",
    "CELERY_BROKER_URL": "redis://localhost:6379/1",
    "CELERY_RESULT_BACKEND": "redis://localhost:6379/2",
    "JWT_SECRET_KEY": secrets.token_hex(32),
    "ACME_EMAIL": "test@example.com",
}.items():
    os.environ.setdefault(_key, _value)

from pydantic import ValidationError  # noqa: E402

from app.schemas.dns import DNSRecordCreate  # noqa: E402
from app.schemas.validators import proxy_refusal  # noqa: E402


@pytest.mark.parametrize("name,rtype", [
    ("@", "A"), ("www", "CNAME"), ("app", "AAAA"), ("rogova.sub", "A"),
])
def test_site_names_can_be_proxied(name, rtype):
    assert proxy_refusal(name, rtype) is None


@pytest.mark.parametrize("name,rtype", [
    ("protonmail._domainkey", "CNAME"), ("_dmarc", "CNAME"), ("_acme-challenge.www", "CNAME"),
    ("@", "MX"), ("@", "TXT"), ("mail", "NS"),
])
def test_service_records_are_not_proxied(name, rtype):
    assert proxy_refusal(name, rtype)


def test_create_rejects_proxied_dkim():
    with pytest.raises(ValidationError):
        DNSRecordCreate(type="CNAME", name="protonmail._domainkey",
                        content="protonmail.domainkey.example.proton.ch", proxied=True)
    record = DNSRecordCreate(type="CNAME", name="protonmail._domainkey",
                             content="protonmail.domainkey.example.proton.ch")
    assert record.proxied is False
