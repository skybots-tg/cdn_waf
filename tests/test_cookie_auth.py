"""
Запасной вход в API по cookie ``access_token`` — только для чтения.

Страницы панели авторизованы этой cookie, а их скрипты зовут API через fetch
с Bearer-токеном из localStorage. 23.09.2026 браузер держал старый main.js из
кэша, токен в запросы не подставлялся, и экраны аналитики получили 401 при
живой сессии. Теперь GET/HEAD без заголовка берут токен из cookie, а
изменяющие запросы без заголовка по-прежнему отклоняются (иначе CSRF).
"""

import asyncio
import os
import secrets
from types import SimpleNamespace

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

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app.core import security  # noqa: E402
from app.services import user_service  # noqa: E402

USER = SimpleNamespace(id=1, is_active=True, is_superuser=True, email="owner@example.com")


@pytest.fixture(autouse=True)
def fake_users(monkeypatch):
    async def get_by_id(self, user_id):
        return USER if user_id == 1 else None
    monkeypatch.setattr(user_service.UserService, "__init__", lambda self, db: None)
    monkeypatch.setattr(user_service.UserService, "get_by_id", get_by_id)


def _request(method, cookie=None):
    return SimpleNamespace(method=method, cookies={"access_token": cookie} if cookie else {})


def _call(method, cookie=None, credentials=None):
    return asyncio.run(security.get_current_user(
        request=_request(method, cookie), credentials=credentials, db=None,
    ))


def test_get_uses_cookie_when_no_header():
    token = security.create_access_token({"sub": "1"})
    assert _call("GET", cookie=token) is USER


def test_post_ignores_cookie():
    token = security.create_access_token({"sub": "1"})
    with pytest.raises(HTTPException) as err:
        _call("POST", cookie=token)
    assert err.value.status_code == 401


def test_no_cookie_no_header_is_401():
    with pytest.raises(HTTPException) as err:
        _call("GET")
    assert err.value.status_code == 401


def test_header_wins_over_cookie():
    good = security.create_access_token({"sub": "1"})
    creds = SimpleNamespace(credentials=good)
    assert _call("DELETE", cookie="garbage", credentials=creds) is USER


def test_refresh_token_in_cookie_is_rejected():
    refresh = security.create_refresh_token({"sub": "1"}) if hasattr(security, "create_refresh_token") else None
    if refresh is None:
        pytest.skip("нет refresh-токенов")
    with pytest.raises(HTTPException):
        _call("GET", cookie=refresh)
