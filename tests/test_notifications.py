"""
Уведомления вкладки «Notifications»: переключатели, вебхуки, отбор событий.

До 23.09.2026 вкладка только показывала «saved»: переключатели не сохранялись,
а напоминаний о сертификатах, всплесков атак, пределов панели и недельных
отчётов не существовало.
"""

import asyncio
import os
import secrets
from datetime import datetime, timedelta

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

from app.services import notifications  # noqa: E402
from app.services.alert_service import AlertService  # noqa: E402
from app.tasks import notification_tasks as nt  # noqa: E402


@pytest.mark.parametrize("url", [
    "https://hooks.slack.com/services/T/B/X", "https://discord.com/api/webhooks/1/abc",
])
def test_public_https_webhooks_pass(url):
    assert notifications.validate_webhook_url(url) == url


@pytest.mark.parametrize("url", [
    "http://hooks.slack.com/x", "https://localhost/x", "https://127.0.0.1/x",
    "https://10.0.0.5/hook", "https://192.168.1.1/", "https://[::1]/x", "ftp://example.com", "",
])
def test_internal_or_plain_webhooks_rejected(url):
    with pytest.raises(ValueError):
        notifications.validate_webhook_url(url)


def test_stored_webhooks_are_revalidated():
    raw = '[{"url": "https://example.com/a"}, {"url": "http://example.com/b"}, "мусор"]'
    assert notifications.parse_webhooks(raw) == [{"url": "https://example.com/a"}]
    assert notifications.parse_webhooks("не json") == []


def test_renewed_certificate_is_not_reported():
    now = datetime(2026, 9, 23)
    certs = [
        ("perek.us", "perek.us", now + timedelta(days=5)),     # старая копия
        ("perek.us", "perek.us", now + timedelta(days=85)),    # продлённая
        ("skybots.ru", "rogova.skybots.ru", now + timedelta(days=3)),
        ("skybots.ru", "old.skybots.ru", now - timedelta(days=1)),
        ("skybots.ru", "fine.skybots.ru", now + timedelta(days=40)),
    ]
    names = [name for name, _ in nt.select_expiring(certs, now)]
    assert names == ["old.skybots.ru", "rogova.skybots.ru"]


def test_spike_needs_volume_and_contrast():
    current = {1: 1200, 2: 150, 3: 600, 4: 900}
    baseline = {1: 24 * 30, 3: 24 * 200, 4: 0}
    spikes = nt.detect_spikes(current, baseline)
    # 1: 1200 против обычных 30/ч — всплеск; 2: мало; 3: обычный фон 200/ч;
    # 4: тихий сайт — сравнение с полом 20/ч, 900 ≥ 100.
    assert [s[0] for s in spikes] == [1, 4]


def _metrics(requests, **extra):
    base = {"total_requests": requests, "status_5xx": 0, "cache_hit_ratio": 50.0,
            "total_bandwidth": 1024 ** 2, "threats_blocked": 0}
    base.update(extra)
    return base


def test_weekly_report_text():
    start, end = datetime(2026, 9, 14), datetime(2026, 9, 21)
    rows = [
        {"name": "perek.us", "cur": _metrics(2000, status_5xx=40, threats_blocked=12),
         "prev": _metrics(1000), "visitors": 350},
        {"name": "quiet.ru", "cur": _metrics(0), "prev": _metrics(0), "visitors": 0},
    ]
    text = nt.format_weekly(rows, start, end)
    assert "14.09 – 20.09.2026" in text
    assert "<b>perek.us</b>: 2 000 запр. (+100%)" in text
    assert "5xx 2.0%" in text and "блок 12" in text
    assert "quiet.ru" not in text


@pytest.fixture
def channels(monkeypatch):
    sent, hooks = [], []

    async def telegram(text, parse_mode="HTML"):
        sent.append(text)
        return True

    async def webhooks(items, **kwargs):
        hooks.append((items, kwargs["event"]))
        return len(items)

    prefs = {**notifications.defaults(), "downtime": False,
             "webhooks": [{"url": "https://example.com/hook"}]}

    async def load(fresh=False):
        return prefs

    monkeypatch.setattr(AlertService, "send_telegram", staticmethod(telegram))
    monkeypatch.setattr(notifications, "post_webhooks", webhooks)
    monkeypatch.setattr(notifications, "load", load)
    return sent, hooks


def test_switched_off_category_is_silent(channels):
    sent, hooks = channels
    asyncio.run(AlertService.origin_down("main", "198.51.100.1", "perek.us", 3))
    assert sent == [] and hooks == []


def test_node_alerts_ignore_switches_and_reach_webhooks(channels):
    sent, hooks = channels
    asyncio.run(AlertService.edge_node_down("node-6", "80.87.197.79", "timeout"))
    assert len(sent) == 1 and "Edge-нода недоступна" in sent[0]
    assert hooks == [([{"url": "https://example.com/hook"}], None)]


def test_plain_text_for_webhooks():
    assert notifications.plain_text("<b>Домен:</b> a&amp;b<br>ok") == "Домен: a&b\nok"
