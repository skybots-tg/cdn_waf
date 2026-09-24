"""
Классы трафика (app/services/traffic_class.py) и фильтр «люди / боты».

До 24.09.2026 аналитика делила запросы только по User-Agent, и всё, что
представлялось Chrome или Safari, считалось браузером. User-Agent в тестах —
настоящие, из логов доменов панели за сентябрь 2026.
"""

import os
import secrets
from datetime import datetime, timedelta

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
from sqlalchemy.dialects import postgresql  # noqa: E402

from app.api import internal_logs  # noqa: E402
from app.services import analytics_query as aq  # noqa: E402
from app.services import ip_networks  # noqa: E402
from app.services import traffic_class as tc  # noqa: E402

IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/27.0 Mobile/24A437 Safari/604.1"
)
IPHONE_WEBVIEW = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Mobile/15E148"
)
CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/153.0.0.0 Safari/537.36"
)
OPERA = CHROME.replace("Chrome/153.0.0.0", "Chrome/151.0.0.0") + " OPR/135.0.0.0"
YANDEX_APP = (
    "Mozilla/5.0 (Linux; arm_64; Android 16; I2405) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.7871.114 YaBrowser/26.1.0.114 Mobile Safari/537.36"
)
CUBOT = (
    "Mozilla/5.0 (Linux; Android 10; CUBOT X30) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Mobile Safari/537.36"
)


@pytest.mark.parametrize("ua, expected", [
    ("Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)", tc.SEARCH),
    ("Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/153.0.8010.52 Mobile Safari/537.36 (compatible; Google-InspectionTool/1.0;)", tc.SEARCH),
    ("Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)", tc.SEARCH),
    ("Mozilla/5.0 (compatible; YandexFavicons/1.0; +http://yandex.com/bots)", tc.SEARCH),
    ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.4; +https://openai.com/gptbot)", tc.AI),
    ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0; +claudebot@anthropic.com)", tc.AI),
    ("Mozilla/5.0 (compatible; AhrefsBot/7.0; +http://ahrefs.com/robot/)", tc.SEO),
    # У превью Telegram в UA есть «TwitterBot» — это превью, а не «прочий бот».
    ("Mozilla/5.0 (compatible; TelegramBot/1.0 like Linux)", tc.PREVIEW),
    ("OdklBot/1.0 (share@odnoklassniki.ru)", tc.PREVIEW),
    ("Mozilla/5.0 (compatible; archive.org_bot +http://archive.org/details/archive.org_bot) Zeno/7d76126", tc.ARCHIVE),
    ("MedcardBot/1.0", tc.BOT),
    ("curl/8.16.0", tc.TOOL),
    ("python-requests/2.31.0", tc.TOOL),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
     "HeadlessChrome/153.0.0.0 Safari/537.36", tc.TOOL),
    # Обрезанный UA без версии браузера — скрипт, а не браузер.
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", tc.TOOL),
    ("", tc.TOOL),
    (None, tc.TOOL),
    ("Happ/4.4.1/Android/17891107313301967518", tc.APP),
    ("Telegram/34639 CFNetwork/3896.100.1.2.1 Darwin/27.0.0", tc.APP),
    (IPHONE, None),
    (IPHONE_WEBVIEW, None),
    (CHROME, None),
    (OPERA, None),
    # Приложение Яндекса и Яндекс Браузер — люди, не YandexBot.
    (YANDEX_APP, None),
    # «bot» в модели телефона — не бот.
    (CUBOT, None),
])
def test_ua_class(ua, expected):
    assert tc.ua_class(ua) == expected


@pytest.mark.parametrize("path, status, expected", [
    ("/.env", 404, True),
    ("/.env.production", 403, True),
    ("/.git/config", 404, True),
    ("/wp-login.php", 405, True),
    ("/api/.env", 404, True),
    # Сайт на WordPress отдаёт свои пути — его посетители не сканеры.
    ("/wp-login.php", 200, False),
    ("/wp-content/uploads/a.jpg", 200, False),
    ("/ru/journal/app-cost/", 404, False),
    ("/.well-known/acme-challenge/x", 404, False),
    ("/.env", None, False),
])
def test_is_probe(path, status, expected):
    assert tc.is_probe(path, status) is expected


def test_classify_uses_network():
    # Браузер из дома — человек, из дата-центра — пока «hosted».
    assert tc.classify(CHROME, "/", 200, hosting=False) == tc.HUMAN
    assert tc.classify(CHROME, "/", 200, hosting=True) == tc.HOSTED
    # Приложение на телефоне — люди, та же библиотека на сервере — скрипт.
    assert tc.classify("okhttp/5.3.0", "/api", 200, hosting=False) == tc.APP
    assert tc.classify("okhttp/5.3.0", "/api", 200, hosting=True) == tc.TOOL
    # Проба важнее UA: сканер под видом iPhone.
    assert tc.classify(IPHONE, "/.env", 404, hosting=True) == tc.SCANNER
    # Объявленный бот остаётся ботом из любой сети.
    assert tc.classify("Mozilla/5.0 (compatible; YandexBot/3.0)", "/", 200, hosting=True) == tc.SEARCH


def test_people_and_labels():
    assert set(tc.PEOPLE) == {tc.HUMAN, tc.VPN, tc.APP}
    classes = {tc.HUMAN, tc.VPN, tc.APP, tc.HOSTED, tc.SEARCH, tc.AI, tc.SEO, tc.PREVIEW,
               tc.MONITOR, tc.ARCHIVE, tc.BOT, tc.TOOL, tc.SCANNER}
    assert set(tc.LABELS) == classes
    # client_class — VARCHAR(10)
    assert max(len(c) for c in classes) <= 10


@pytest.mark.parametrize("asn, org, expected", [
    (16509, "AMAZON-02", True),
    (15169, "GOOGLE", True),
    (16276, "OVH SAS", True),
    (99999, "Hostkey B.v.", True),
    (99998, "Serv.host Group Ltd", True),
    (99997, "Ouiheberg SARL", True),
    (21299, "Kar-Tel LLC", False),
    (3216, "PJSC Vimpelcom", False),
    (8402, "Corbina Telecom", False),
    # iCloud Private Relay и WARP — люди, хоть это Akamai и Cloudflare.
    (36183, "Akamai Technologies, Inc.", False),
    (13335, "Cloudflare, Inc.", False),
    (16591, "Google Fiber Inc.", False),
    (None, None, False),
])
def test_is_hosting(asn, org, expected):
    assert ip_networks.is_hosting(asn, org) is expected


def test_lookup_without_database(monkeypatch, tmp_path):
    # Без файла базы приём логов не падает: ASN просто пустой.
    monkeypatch.setattr(ip_networks, "DB_PATH", tmp_path / "missing.mmdb")
    monkeypatch.setattr(ip_networks, "_reader", ip_networks._Reader())
    assert ip_networks.lookup("8.8.8.8") == (None, None)
    assert ip_networks.lookup(None) == (None, None)


def test_row_gets_class(monkeypatch):
    monkeypatch.setattr(ip_networks, "lookup", lambda ip: (16509, "AMAZON-02"))
    line = {
        "timestamp": "2026-09-24T04:26:22+03:00", "domain": "lampwork.dev",
        "client_ip": "54.221.34.70", "method": "GET", "path": "/ru/", "status": "200",
        "bytes_sent": "1000", "user_agent": CHROME,
    }
    row = internal_logs._row(line, node_id=1, domain_id=15, host="lampwork.dev")
    assert row["asn"] == 16509
    assert row["client_class"] == tc.HOSTED
    line.update(path="/.env", status="404")
    assert internal_logs._row(line, 1, 15, "lampwork.dev")["client_class"] == tc.SCANNER


def test_filtered_period_reads_raw_logs_only():
    now = datetime(2026, 9, 24, 12, 30)
    w = aq.Window("7d", now - timedelta(days=7), now, "hour")
    # Без фильтра прошедшие часы — из свода, с фильтром — всё из сырых логов.
    assert set(aq._parts(w, now)) == {"raw", "hourly"}
    assert aq._parts(w, now, traffic="people") == {"raw": (w.start, w.end)}
    assert aq._parts(w, now, traffic="all") == aq._parts(w, now)
    # Полгода с фильтром: только то, что осталось в сырых логах.
    w6 = aq.Window("6m", now - timedelta(days=180), now, "day")
    start, end = aq._parts(w6, now, traffic="bots")["raw"]
    assert start == aq.raw_floor(now) and end == now


def _sql(conditions):
    return " AND ".join(
        str(c.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for c in conditions
    )


def test_traffic_filter_sql():
    assert aq.traffic_filter("all") == [] and aq.traffic_filter(None) == []
    people = _sql(aq.traffic_filter("people"))
    assert "client_class IN ('human', 'vpn', 'app')" in people
    bots = _sql(aq.traffic_filter("bots"))
    # Строки без класса (до разметки) — не люди.
    assert "coalesce(request_logs.client_class, '') NOT IN ('human', 'vpn', 'app')" in bots
