"""Basic tests for CDN/WAF application."""
import pytest
from unittest.mock import patch, MagicMock


def test_config_loads():
    """Settings can be instantiated with required env vars."""
    from app.core.config import Settings
    with patch.dict("os.environ", {
        "SECRET_KEY": "test-secret",
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db",
        "REDIS_URL": "redis://localhost:6379/0",
        "CELERY_BROKER_URL": "redis://localhost:6379/1",
        "CELERY_RESULT_BACKEND": "redis://localhost:6379/2",
        "JWT_SECRET_KEY": "jwt-test-secret",
        "ACME_EMAIL": "test@example.com",
    }):
        s = Settings()
        assert s.APP_NAME == "FlareCloud"
        assert s.DEBUG is True
        assert "localhost" in str(s.DATABASE_URL)


def test_password_hashing():
    """Password hash round-trip works."""
    from app.core.security import get_password_hash, verify_password
    pw = "TestPassword123!"
    hashed = get_password_hash(pw)
    assert verify_password(pw, hashed)
    assert not verify_password("wrong", hashed)


def test_jwt_round_trip():
    """JWT access token can be created and decoded."""
    from app.core.security import create_access_token, decode_token
    token = create_access_token({"sub": "42"})
    payload = decode_token(token)
    assert payload["sub"] == "42"
    assert payload["type"] == "access"


def test_crypto_service_round_trip():
    """CryptoService encrypts and decrypts correctly."""
    from app.services.crypto_service import CryptoService, ENCRYPTED_PREFIX
    plaintext = "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----"
    encrypted = CryptoService.encrypt(plaintext)
    assert encrypted.startswith(ENCRYPTED_PREFIX)
    assert encrypted != plaintext
    decrypted = CryptoService.decrypt(encrypted)
    assert decrypted == plaintext


def test_crypto_service_idempotent():
    """Encrypting already-encrypted data is a no-op."""
    from app.services.crypto_service import CryptoService
    plaintext = "some-key-data"
    encrypted = CryptoService.encrypt(plaintext)
    double_encrypted = CryptoService.encrypt(encrypted)
    assert encrypted == double_encrypted


def test_crypto_decrypt_if_encrypted_passthrough():
    """decrypt_if_encrypted returns plain text as-is."""
    from app.services.crypto_service import CryptoService
    assert CryptoService.decrypt_if_encrypted("plain-text") == "plain-text"
    assert CryptoService.decrypt_if_encrypted(None) is None
    assert CryptoService.decrypt_if_encrypted("") == ""


def test_parse_waf_conditions():
    """WAF conditions JSON parsing works."""
    import json
    from app.api.internal import _parse_waf_conditions
    assert _parse_waf_conditions(None) is None
    assert _parse_waf_conditions("") is None
    assert _parse_waf_conditions("not json") is None
    result = _parse_waf_conditions(json.dumps({"path": "/admin.*"}))
    assert result["path"] == "/admin.*"


def test_analytics_time_range():
    """analytics_query.window: начало периода выровнено по шагу графика."""
    from app.services.analytics_query import window
    from datetime import datetime, timedelta
    now = datetime(2026, 9, 23, 10, 37, 12)
    w24 = window("24h", now)
    assert w24.start == datetime(2026, 9, 22, 10, 0) and w24.bucket == "hour"
    w7 = window("7d", now)
    assert w7.start == datetime(2026, 9, 16, 10, 0)
    assert window("30d", now).start == datetime(2026, 8, 24)
    assert window("1h", now).start == datetime(2026, 9, 23, 9, 37)
    assert window("24h", now).previous().end == w24.start
