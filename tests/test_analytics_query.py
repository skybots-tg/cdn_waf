"""
Слой запросов аналитики: из каких источников собирается период и как
считаются производные метрики.

До 23.09.2026 «7/30 дней» брали только суточный свод (без сегодняшнего дня),
а «24 часа» — почасовой, отстававший на час. Здесь проверяется, что любой
период покрыт источниками без дыр и без перекрытий.
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

from app.services import analytics_query as aq  # noqa: E402

NOW = datetime(2026, 9, 23, 10, 37, 12)


def _covered(parts):
    """Отрезки источников по порядку — должны идти встык."""
    return sorted(parts.values(), key=lambda p: p[0])


@pytest.mark.parametrize("range_str", ["24h", "7d", "30d", "90d", "6m"])
def test_sources_cover_window_without_gaps(range_str):
    w = aq.window(range_str, NOW)
    spans = _covered(aq._parts(w, NOW))
    assert spans[0][0] == w.start
    assert spans[-1][1] == w.end
    for (a_start, a_end), (b_start, b_end) in zip(spans, spans[1:]):
        assert a_end == b_start, (range_str, spans)


def test_current_hour_comes_from_raw_logs():
    parts = aq._parts(aq.window("24h", NOW), NOW)
    assert parts["raw"] == (datetime(2026, 9, 23, 10, 0), NOW)
    assert parts["hourly"][1] == datetime(2026, 9, 23, 10, 0)


def test_today_is_part_of_30_days():
    """Раньше 30 дней считались по суточному своду и теряли сегодняшний день."""
    parts = aq._parts(aq.window("30d", NOW), NOW)
    assert "daily" not in parts
    assert parts["raw"][1] == NOW


def test_six_months_uses_daily_for_old_days():
    parts = aq._parts(aq.window("6m", NOW), NOW)
    assert "daily" in parts and "hourly" in parts
    assert parts["daily"][1] == parts["hourly"][0]


def test_last_hour_is_raw_only():
    assert set(aq._parts(aq.window("1h", NOW), NOW)) == {"raw"}


def test_previous_window_is_adjacent_and_same_length():
    w = aq.window("7d", NOW)
    prev = w.previous()
    assert prev.end == w.start and prev.span == w.span


def test_previous_window_of_past_has_no_raw_part():
    """Прошлый период целиком в прошлом — сырые логи текущего часа не нужны."""
    prev = aq.window("24h", NOW).previous()
    assert "raw" not in aq._parts(prev, NOW)


def _metrics(**values):
    m = aq.Metrics()
    for k, v in values.items():
        m.values[k] = v
    return m


def test_cache_ratio_like_cloudflare():
    d = _metrics(total_requests=200, cache_hits=50, cache_misses=30, cache_bypass=20,
                 total_bytes_sent=1000, cached_bytes=400).as_dict()
    assert d["cache_hit_ratio"] == 25.0          # от всех запросов
    assert d["cacheable_hit_ratio"] == 50.0      # от кэшируемых
    assert d["uncached_requests"] == 150
    assert d["bandwidth_saved_ratio"] == 40.0


def test_empty_metrics_do_not_divide_by_zero():
    d = aq.Metrics().as_dict()
    assert d["cache_hit_ratio"] == 0 and d["error_rate"] == 0 and d["avg_response_time"] == 0


def test_weighted_response_time():
    m = aq.Metrics()
    m.values["total_requests"] = 4
    m.rt_sum = 400.0
    assert m.avg_response_time == 100.0


def test_change_percent():
    assert aq._change(150, 100) == 50.0
    assert aq._change(50, 100) == -50.0
    assert aq._change(10, 0) is None


def test_iso_marks_utc():
    assert aq.iso(datetime(2026, 9, 23, 1, 2, 3)) == "2026-09-23T01:02:03Z"
    assert aq.iso(None) is None
