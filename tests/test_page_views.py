"""
Просмотры страниц и посетители на экранах аналитики.

До 24.09.2026 экраны считали только запросы: одна страница — это десятки
запросов за CSS, JS и картинками, и по ним не понять, сколько страниц
посмотрели и сколько было людей.
"""

import os
import re
import secrets

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

from collections import namedtuple  # noqa: E402

from sqlalchemy.dialects import postgresql  # noqa: E402

from app.services import analytics_aggregation as agg  # noqa: E402
from app.services import analytics_query as aq  # noqa: E402


def _sql(expr) -> str:
    return str(expr.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_page_view_rule():
    sql = _sql(agg.page_view_expr())
    assert "request_logs.method = 'GET'" in sql
    # 2xx и 304 (страница из кэша браузера), но не 301 и не 404
    assert "BETWEEN 200 AND 299" in sql and "status_code = 304" in sql
    # страница — без расширения или .html; /api/ — не страницы
    assert r"'\.[A-Za-z0-9]{1,12}$'" in sql and r"'\.html?$'" in sql
    # psycopg2-диалект теста удваивает %, asyncpg в проде — нет
    assert "NOT LIKE '/api/%" in sql
    # вызовы API мобильных приложений — не просмотры
    assert "coalesce(request_logs.client_class, '') != 'app'" in sql


def test_page_view_path_regex_matches_postgres_intent():
    # Та же регулярка, что уходит в Postgres: файл — расширение до 12 символов.
    is_file = re.compile(r"\.[A-Za-z0-9]{1,12}$")
    for page in ("/", "/ru/journal/app-cost/", "/work", "/brief/view/abc"):
        assert not is_file.search(page)
    # manifest.webmanifest браузер берёт с каждой страницей — это не просмотр
    for asset in ("/_astro/Lamp.BDjW_UKr.css", "/media/work/perek/log-en.mp4", "/favicon.ico",
                  "/robots.txt", "/manifest.webmanifest"):
        assert is_file.search(asset)


def test_page_views_in_summaries_and_totals():
    assert "page_views" in agg._HOURLY_FIELDS
    assert "page_views" in aq.FIELDS
    assert "page_views" in {m.name for m in agg.raw_metrics()}
    Row = namedtuple("Row", aq.FIELDS)
    m = aq.Metrics()
    m.add(Row(**{f: 0 for f in aq.FIELDS} | {"total_requests": 40, "page_views": 3}))
    data = m.as_dict()
    assert data["total_requests"] == 40 and data["page_views"] == 3


def test_series_and_top_metrics():
    series = re.compile(aq.SERIES_PATTERN)
    for name in ("requests", "page_views", "visitors", "bandwidth"):
        assert series.match(name)
    top = re.compile(aq.TOP_METRIC_PATTERN)
    assert all(top.match(m) for m in ("requests", "views", "visitors"))
    assert not top.match("bytes")
