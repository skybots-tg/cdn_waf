"""Запросы аналитики для экранов панели: итоги, ряды, топы, прошлый период.

Один слой для всех экранов (домен, общая аналитика, CDN, WAF, дашборд, ноды),
чтобы цифры в разных местах сходились. Любой период складывается из трёх
источников, каждый — на своём отрезке:

* сырые логи (``request_logs``) — текущий час, а для «последнего часа» весь
  период: в сводах текущего часа ещё нет или он неполный;
* почасовой свод — прошедшие часы (хранится 90 дней, пересчитывается каждые
  5 минут, см. ``analytics_aggregation``);
* суточный свод — дни старше почасового хранения (для «6 месяцев»).

До 23.09.2026 «7/30 дней» брали только суточный свод, в котором нет
сегодняшнего дня, а «24 часа» — почасовой, отстававший на час.

Время везде UTC без зоны (как в БД); наружу отдаётся ISO с «Z», а переводит
его в местное время браузер.

Фильтр трафика (``traffic``: people/bots, с 24.09.2026) опирается на класс
строки в сырых логах, а в сводах его нет. С фильтром весь период считается
по сырым логам, то есть за последние 30 дней (флаг ``partial`` у 90 дней и
полугода).

Группировки по выражениям (date_trunc, CASE, regexp) идут по номеру колонки:
asyncpg передаёт литералы параметрами, и одно и то же выражение в SELECT и в
GROUP BY для Postgres — разные выражения (GroupingError, сломавший почасовой
свод).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import and_, case, desc, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.analytics import DailyStats, ErrorStats, GeoStats, HourlyStats, TopPathsStats
from app.models.log import RequestLog
from app.services import ip_networks, traffic_class as tc
from app.services.analytics_aggregation import page_view_expr, raw_metrics

RANGE_PATTERN = r"^(1h|24h|7d|30d|90d|6m)$"
TRAFFIC_PATTERN = r"^(all|people|bots)$"
# Что считают топы: запросы, просмотры страниц или посетителей (уникальные IP).
TOP_METRIC_PATTERN = r"^(requests|views|visitors)$"

# Длина периода и шаг графика.
RANGES: Dict[str, tuple] = {
    "1h": (timedelta(hours=1), "minute"),
    "24h": (timedelta(hours=24), "hour"),
    "7d": (timedelta(days=7), "hour"),
    "30d": (timedelta(days=30), "day"),
    "90d": (timedelta(days=90), "day"),
    "6m": (timedelta(days=180), "day"),
}

RAW_RETENTION_DAYS = getattr(settings, "ANALYTICS_RAW_LOGS_RETENTION", 30)
HOURLY_RETENTION_DAYS = getattr(settings, "ANALYTICS_HOURLY_RETENTION", 90)

FIELDS = (
    "total_requests", "page_views", "total_bytes_sent", "status_2xx", "status_3xx",
    "status_4xx", "status_5xx", "cache_hits", "cache_misses", "cache_bypass",
    "cached_bytes", "waf_blocked", "waf_challenged", "rate_limited",
    "total_bytes_received", "origin_requests",
)


# --- период --------------------------------------------------------------


def floor(dt: datetime, unit: str) -> datetime:
    if unit == "minute":
        return dt.replace(second=0, microsecond=0)
    if unit == "hour":
        return dt.replace(minute=0, second=0, microsecond=0)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def step(unit: str) -> timedelta:
    return {"minute": timedelta(minutes=1), "hour": timedelta(hours=1)}.get(unit, timedelta(days=1))


@dataclass(frozen=True)
class Window:
    range: str
    start: datetime
    end: datetime
    bucket: str

    @property
    def span(self) -> timedelta:
        return self.end - self.start

    def previous(self) -> "Window":
        """Такой же период прямо перед этим — для «+12% к прошлому»."""
        return Window(self.range, self.start - self.span, self.start, self.bucket)


def window(range_str: str, now: Optional[datetime] = None) -> Window:
    now = now or datetime.utcnow()
    span, bucket = RANGES.get(range_str, RANGES["24h"])
    return Window(range_str, floor(now - span, bucket), now, bucket)


def _parts(w: Window, now: Optional[datetime] = None, traffic: Optional[str] = None) -> Dict[str, tuple]:
    """Какой источник покрывает какой отрезок периода."""
    now = now or datetime.utcnow()
    if w.bucket == "minute":
        return {"raw": (w.start, w.end)}
    if _filtered(traffic):
        start = max(w.start, raw_floor(now))
        return {"raw": (start, w.end)} if start < w.end else {}
    current_hour = floor(now, "hour")
    hourly_floor = floor(now - timedelta(days=HOURLY_RETENTION_DAYS - 1), "day")
    parts: Dict[str, tuple] = {}
    raw_start = max(w.start, current_hour)
    if raw_start < w.end:
        parts["raw"] = (raw_start, w.end)
    hourly_start, hourly_end = max(w.start, hourly_floor), min(w.end, current_hour)
    if hourly_start < hourly_end:
        parts["hourly"] = (hourly_start, hourly_end)
    if w.start < hourly_floor:
        parts["daily"] = (w.start, min(hourly_floor, w.end))
    return parts


def raw_floor(now: Optional[datetime] = None) -> datetime:
    """С какого момента сырые логи ещё хранятся."""
    now = now or datetime.utcnow()
    return floor(now - timedelta(days=RAW_RETENTION_DAYS), "hour")


def _filtered(traffic: Optional[str]) -> bool:
    return traffic in ("people", "bots")


def traffic_filter(traffic: Optional[str]) -> list:
    """Условие на сырые логи: только люди, только боты или всё."""
    if traffic == "people":
        return [RequestLog.client_class.in_(tc.PEOPLE)]
    if traffic == "bots":
        return [func.coalesce(RequestLog.client_class, literal_column("''")).notin_(tc.PEOPLE)]
    return []


def iso(dt: Optional[datetime]) -> Optional[str]:
    """UTC-время для браузера: без «Z» JS читает его как местное."""
    return dt.isoformat() + "Z" if dt else None


# --- метрики ---------------------------------------------------------------


@dataclass
class Metrics:
    values: Dict[str, int] = field(default_factory=lambda: {f: 0 for f in FIELDS})
    rt_sum: float = 0.0
    ot_sum: float = 0.0  # сумма времени ответа origin (мс) по origin_requests

    def add(self, row: Any) -> None:
        for f in FIELDS:
            self.values[f] += int(getattr(row, f, 0) or 0)
        self.rt_sum += float(getattr(row, "rt_sum", 0) or 0)
        self.ot_sum += float(getattr(row, "ot_sum", 0) or 0)

    @property
    def requests(self) -> int:
        return self.values["total_requests"]

    @property
    def avg_response_time(self) -> float:
        return round(self.rt_sum / self.requests, 1) if self.requests else 0.0

    def as_dict(self) -> Dict[str, Any]:
        v = self.values
        requests = v["total_requests"]
        bandwidth = v["total_bytes_sent"]
        threats = v["waf_blocked"] + v["waf_challenged"]
        return {
            "total_requests": requests,
            "page_views": v["page_views"],
            "cached_requests": v["cache_hits"],
            "uncached_requests": max(requests - v["cache_hits"], 0),
            "total_bandwidth": bandwidth,
            "cached_bandwidth": v["cached_bytes"],
            "uncached_bandwidth": max(bandwidth - v["cached_bytes"], 0),
            # Как у Cloudflare: доля запросов, отданных из кэша, от всех.
            "cache_hit_ratio": round(v["cache_hits"] / requests * 100, 1) if requests else 0.0,
            # Доля кэша среди того, что вообще кэшируется (без динамики).
            "cacheable_hit_ratio": _ratio(v["cache_hits"], v["cache_hits"] + v["cache_misses"] + v["cache_bypass"]),
            "bandwidth_saved_ratio": _ratio(v["cached_bytes"], bandwidth),
            "cache_hits": v["cache_hits"],
            "cache_misses": v["cache_misses"],
            "cache_bypass": v["cache_bypass"],
            "threats_blocked": threats,
            "waf_blocked": v["waf_blocked"],
            "waf_challenged": v["waf_challenged"],
            "rate_limited": v["rate_limited"],
            "status_2xx": v["status_2xx"],
            "status_3xx": v["status_3xx"],
            "status_4xx": v["status_4xx"],
            "status_5xx": v["status_5xx"],
            "error_rate": _ratio(v["status_4xx"] + v["status_5xx"], requests),
            "avg_response_time": self.avg_response_time,
            # Время ответа самого сайта — у запросов, дошедших до origin.
            "avg_origin_time": (
                round(self.ot_sum / v["origin_requests"], 1) if v["origin_requests"] else None
            ),
            "origin_requests": v["origin_requests"],
            "bytes_received": v["total_bytes_received"],
        }


def _ratio(part: float, whole: float) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def _change(current: float, previous: float) -> Optional[float]:
    """Изменение к прошлому периоду в процентах; None — сравнивать не с чем."""
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)


def _domain_filter(column, domain_ids: Optional[Sequence[int]]):
    if domain_ids is None:
        return []
    return [column.in_(list(domain_ids) or [-1])]


def _key_col(model, group_by: Optional[str]):
    if group_by == "domain":
        return [model.domain_id.label("key")]
    if group_by == "node":
        return [model.edge_node_id.label("key")]
    return []


async def totals(
    db: AsyncSession,
    w: Window,
    domain_ids: Optional[Sequence[int]] = None,
    group_by: Optional[str] = None,
    traffic: Optional[str] = None,
) -> Dict[Any, Metrics]:
    """Итоги периода; ``group_by`` — 'domain' или 'node' (ключ словаря)."""
    out: Dict[Any, Metrics] = {}

    def put(rows):
        for row in rows:
            key = getattr(row, "key", None) if group_by else None
            out.setdefault(key, Metrics()).add(row)

    parts = _parts(w, traffic=traffic)
    if "hourly" in parts:
        s, e = parts["hourly"]
        keys = _key_col(HourlyStats, group_by)
        q = select(
            *keys,
            *[func.coalesce(func.sum(getattr(HourlyStats, f)), 0).label(f) for f in FIELDS],
            func.coalesce(func.sum(HourlyStats.avg_response_time * HourlyStats.total_requests), 0).label("rt_sum"),
            func.coalesce(func.sum(HourlyStats.avg_origin_time * HourlyStats.origin_requests), 0).label("ot_sum"),
        ).where(HourlyStats.hour >= s, HourlyStats.hour < e, *_domain_filter(HourlyStats.domain_id, domain_ids))
        if keys:
            q = q.group_by(*keys)
        put((await db.execute(q)).all())
    if "daily" in parts and group_by != "node":
        s, e = parts["daily"]
        keys = _key_col(DailyStats, group_by)
        q = select(
            *keys,
            *[func.coalesce(func.sum(getattr(DailyStats, f)), 0).label(f) for f in FIELDS],
            func.coalesce(func.sum(DailyStats.avg_response_time * DailyStats.total_requests), 0).label("rt_sum"),
            func.coalesce(func.sum(DailyStats.avg_origin_time * DailyStats.origin_requests), 0).label("ot_sum"),
        ).where(DailyStats.day >= s.date(), DailyStats.day < e.date(), *_domain_filter(DailyStats.domain_id, domain_ids))
        if keys:
            q = q.group_by(*keys)
        put((await db.execute(q)).all())
    if "raw" in parts:
        s, e = parts["raw"]
        keys = _key_col(RequestLog, group_by)
        q = select(
            *keys,
            *raw_metrics(),
            func.coalesce(func.sum(RequestLog.request_time), 0).label("rt_sum"),
            func.coalesce(func.sum(RequestLog.upstream_time), 0).label("ot_sum"),
        ).where(
            RequestLog.timestamp >= s, RequestLog.timestamp < e,
            RequestLog.domain_id.isnot(None),
            *_domain_filter(RequestLog.domain_id, domain_ids),
            *traffic_filter(traffic),
        )
        if keys:
            q = q.group_by(*keys)
        put((await db.execute(q)).all())
    if not group_by:
        out.setdefault(None, Metrics())
    return out


async def unique_visitors(
    db: AsyncSession, w: Window, domain_ids: Optional[Sequence[int]] = None,
    traffic: Optional[str] = None,
) -> int:
    """Уникальные IP за период.

    Пока период в пределах хранения сырых логов — точный подсчёт. Старше —
    к нему прибавляется сумма суточных уникальных (один человек в разные дни
    считается несколько раз; для 90 дней и полугода это приближение).
    """
    floor_raw = raw_floor()
    raw_start = max(w.start, floor_raw)
    count = (await db.execute(
        select(func.count(func.distinct(RequestLog.client_ip))).where(
            RequestLog.timestamp >= raw_start, RequestLog.timestamp < w.end,
            RequestLog.domain_id.isnot(None),
            *_domain_filter(RequestLog.domain_id, domain_ids),
            *traffic_filter(traffic),
        )
    )).scalar() or 0
    if w.start < floor_raw and not _filtered(traffic):
        count += (await db.execute(
            select(func.coalesce(func.sum(DailyStats.unique_visitors), 0)).where(
                DailyStats.day >= w.start.date(), DailyStats.day < floor_raw.date(),
                *_domain_filter(DailyStats.domain_id, domain_ids),
            )
        )).scalar() or 0
    return int(count)


async def visitors_by_domain(
    db: AsyncSession, w: Window, domain_ids: Optional[Sequence[int]] = None,
    traffic: Optional[str] = None,
) -> Dict[int, int]:
    """Уникальные IP каждого домена за доступную в сырых логах часть периода."""
    rows = (await db.execute(
        select(RequestLog.domain_id, func.count(func.distinct(RequestLog.client_ip)).label("n"))
        .where(
            RequestLog.timestamp >= max(w.start, raw_floor()), RequestLog.timestamp < w.end,
            RequestLog.domain_id.isnot(None),
            *_domain_filter(RequestLog.domain_id, domain_ids),
            *traffic_filter(traffic),
        ).group_by(RequestLog.domain_id)
    )).all()
    return {r.domain_id: int(r.n) for r in rows}


async def response_percentiles(
    db: AsyncSession, w: Window, domain_ids: Optional[Sequence[int]] = None,
    traffic: Optional[str] = None,
) -> Dict[str, Optional[float]]:
    """p50/p95 времени ответа ноды (мс) по сырым логам доступной части периода."""
    row = (await db.execute(
        select(
            func.percentile_cont(0.5).within_group(RequestLog.request_time).label("p50"),
            func.percentile_cont(0.95).within_group(RequestLog.request_time).label("p95"),
            func.percentile_cont(0.95).within_group(RequestLog.upstream_time).label("origin_p95"),
        ).where(
            RequestLog.timestamp >= max(w.start, raw_floor()), RequestLog.timestamp < w.end,
            RequestLog.request_time.isnot(None),
            RequestLog.domain_id.isnot(None),
            *_domain_filter(RequestLog.domain_id, domain_ids),
            *traffic_filter(traffic),
        )
    )).first()
    return {
        "p50_response_time": round(float(row.p50), 1) if row and row.p50 is not None else None,
        "p95_response_time": round(float(row.p95), 1) if row and row.p95 is not None else None,
        "p95_origin_time": round(float(row.origin_p95), 1) if row and row.origin_p95 is not None else None,
    }


async def overview(
    db: AsyncSession, range_str: str, domain_ids: Optional[Sequence[int]] = None,
    traffic: Optional[str] = None,
) -> Dict[str, Any]:
    """Всё для карточек: итоги, посетители, время ответа, изменение к прошлому."""
    w = window(range_str)
    prev = w.previous()
    current = (await totals(db, w, domain_ids, traffic=traffic))[None]
    previous = (await totals(db, prev, domain_ids, traffic=traffic))[None]
    visitors = await unique_visitors(db, w, domain_ids, traffic)
    visitors_prev = await unique_visitors(db, prev, domain_ids, traffic)

    data = current.as_dict()
    prev_data = previous.as_dict()
    data.update(await response_percentiles(db, w, domain_ids, traffic))
    data["unique_visitors"] = visitors
    data["previous"] = {**prev_data, "unique_visitors": visitors_prev}
    data["changes"] = {
        "requests": _change(data["total_requests"], prev_data["total_requests"]),
        "page_views": _change(data["page_views"], prev_data["page_views"]),
        "bandwidth": _change(data["total_bandwidth"], prev_data["total_bandwidth"]),
        "visitors": _change(visitors, visitors_prev),
        "threats": _change(data["threats_blocked"], prev_data["threats_blocked"]),
        "errors": _change(
            data["status_4xx"] + data["status_5xx"],
            prev_data["status_4xx"] + prev_data["status_5xx"],
        ),
        # Доля кэша меняется в процентных пунктах, а не в процентах.
        "cache_hit_ratio": (
            round(data["cache_hit_ratio"] - prev_data["cache_hit_ratio"], 1)
            if prev_data["total_requests"] else None
        ),
    }
    data.update(range=range_str, start=iso(w.start), end=iso(w.end), bucket=w.bucket)
    data["traffic"] = traffic or "all"
    # С фильтром всё считается по сырым логам — за 90 дней и полгода только 30.
    data["partial"] = _filtered(traffic) and w.start < raw_floor()
    return data


# --- ряды для графиков -----------------------------------------------------

SERIES = {
    "requests": lambda v: v["total_requests"],
    "page_views": lambda v: v["page_views"],
    "cached_requests": lambda v: v["cache_hits"],
    "bandwidth": lambda v: v["total_bytes_sent"],
    "cached_bandwidth": lambda v: v["cached_bytes"],
    "threats": lambda v: v["waf_blocked"] + v["waf_challenged"],
    "rate_limited": lambda v: v["rate_limited"],
    "errors_4xx": lambda v: v["status_4xx"],
    "errors_5xx": lambda v: v["status_5xx"],
}


# Ряды графика: из сводов плюс посетители по шагам (из сырых логов).
SERIES_PATTERN = "^(" + "|".join([*SERIES, "visitors"]) + ")$"


def _trunc(unit: str, column):
    return func.date_trunc(literal_column(f"'{unit}'"), column)


async def timeseries(
    db: AsyncSession,
    range_str: str,
    domain_ids: Optional[Sequence[int]] = None,
    metric: str = "requests",
    traffic: Optional[str] = None,
) -> Dict[str, Any]:
    """Ряды по шагам периода, пустые шаги — нулями."""
    w = window(range_str)
    buckets: Dict[datetime, Metrics] = {}

    def put(rows):
        for row in rows:
            key = row.bucket.replace(tzinfo=None) if row.bucket.tzinfo else row.bucket
            buckets.setdefault(floor(key, w.bucket), Metrics()).add(row)

    parts = _parts(w, traffic=traffic)
    if "hourly" in parts:
        s, e = parts["hourly"]
        bucket_col = HourlyStats.hour if w.bucket == "hour" else _trunc(w.bucket, HourlyStats.hour)
        q = select(
            bucket_col.label("bucket"),
            *[func.coalesce(func.sum(getattr(HourlyStats, f)), 0).label(f) for f in FIELDS],
        ).where(
            HourlyStats.hour >= s, HourlyStats.hour < e,
            *_domain_filter(HourlyStats.domain_id, domain_ids),
        ).group_by(literal_column("1"))
        put((await db.execute(q)).all())
    if "daily" in parts:
        s, e = parts["daily"]
        rows = (await db.execute(
            select(
                DailyStats.day.label("day"),
                *[func.coalesce(func.sum(getattr(DailyStats, f)), 0).label(f) for f in FIELDS],
            ).where(
                DailyStats.day >= s.date(), DailyStats.day < e.date(),
                *_domain_filter(DailyStats.domain_id, domain_ids),
            ).group_by(DailyStats.day)
        )).all()
        for row in rows:
            buckets.setdefault(datetime.combine(row.day, datetime.min.time()), Metrics()).add(row)
    if "raw" in parts:
        s, e = parts["raw"]
        q = select(
            _trunc(w.bucket, RequestLog.timestamp).label("bucket"),
            *raw_metrics(),
        ).where(
            RequestLog.timestamp >= s, RequestLog.timestamp < e,
            RequestLog.domain_id.isnot(None),
            *_domain_filter(RequestLog.domain_id, domain_ids),
            *traffic_filter(traffic),
        ).group_by(literal_column("1"))
        put((await db.execute(q)).all())

    points: List[datetime] = []
    t, last = floor(w.start, w.bucket), floor(w.end, w.bucket)
    while t <= last:
        points.append(t)
        t += step(w.bucket)

    empty = Metrics()
    series = {
        name: [fn((buckets.get(p) or empty).values) for p in points]
        for name, fn in SERIES.items()
    }
    visitors = await _visitor_buckets(db, w, domain_ids, traffic)
    series["visitors"] = [visitors.get(p, 0) for p in points]
    fmt = {"minute": "%H:%M", "hour": "%d.%m %H:00", "day": "%d.%m"}[w.bucket]
    return {
        "range": range_str,
        "bucket": w.bucket,
        "timestamps": [iso(p) for p in points],
        "labels": [p.strftime(fmt) for p in points],
        "series": series,
        # Старый формат для экранов, которые просят одну метрику.
        "data": series.get(metric, series["requests"]),
    }


async def _visitor_buckets(
    db: AsyncSession, w: Window, domain_ids: Optional[Sequence[int]], traffic: Optional[str]
) -> Dict[datetime, int]:
    """Уникальные IP по шагам периода.

    Их нельзя сложить из почасового свода (один человек за день — в каждом
    часе), поэтому шаги в пределах 30 дней считаются по сырым логам, а дни
    старше — из суточного свода, где уникальные посчитаны за сутки.
    """
    out: Dict[datetime, int] = {}
    floor_raw = raw_floor()
    start = max(w.start, floor_raw)
    if start < w.end:
        rows = (await db.execute(
            select(
                _trunc(w.bucket, RequestLog.timestamp).label("bucket"),
                func.count(func.distinct(RequestLog.client_ip)).label("n"),
            ).where(
                RequestLog.timestamp >= start, RequestLog.timestamp < w.end,
                RequestLog.domain_id.isnot(None),
                *_domain_filter(RequestLog.domain_id, domain_ids),
                *traffic_filter(traffic),
            ).group_by(literal_column("1"))
        )).all()
        for row in rows:
            key = row.bucket.replace(tzinfo=None) if row.bucket.tzinfo else row.bucket
            out[floor(key, w.bucket)] = out.get(floor(key, w.bucket), 0) + int(row.n)
    if w.bucket == "day" and w.start < floor_raw and not _filtered(traffic):
        rows = (await db.execute(
            select(DailyStats.day, func.coalesce(func.sum(DailyStats.unique_visitors), 0).label("n"))
            .where(DailyStats.day >= w.start.date(), DailyStats.day < floor_raw.date(),
                   *_domain_filter(DailyStats.domain_id, domain_ids))
            .group_by(DailyStats.day)
        )).all()
        for row in rows:
            out[datetime.combine(row.day, datetime.min.time())] = int(row.n)
    return out


# --- топы ------------------------------------------------------------------


def referrer_host_expr():
    return func.substring(RequestLog.referer, literal_column("'^[a-zA-Z]+://([^/:?#]+)'"))


def browser_expr():
    """Браузер по User-Agent; боты, скрипты и сканеры — по классу строки.

    До 24.09.2026 «Scripts» проверялись последними, и headless Chrome или
    python-requests с браузерным UA попадали в Chrome.
    """
    ua = func.lower(func.coalesce(RequestLog.user_agent, literal_column("''")))
    cls = RequestLog.client_class
    by_class = [
        (cls.in_(tc.DECLARED + (tc.BOT,)), literal_column("'Bots'")),
        (cls == literal_column(f"'{tc.SCANNER}'"), literal_column("'Scanners'")),
        (cls == literal_column(f"'{tc.TOOL}'"), literal_column("'Scripts'")),
        (cls == literal_column(f"'{tc.APP}'"), literal_column("'Mobile apps'")),
    ]
    rules = (
        (("%headlesschrome%", "%lighthouse%", "%phantomjs%"), "Scripts"),
        (("%bot%", "%crawl%", "%spider%", "%slurp%"), "Bots"),
        (("% max/%",), "MAX app"),
        (("%telegram%",), "Telegram"),
        (("%yabrowser%",), "Yandex Browser"),
        (("%edg/%",), "Edge"),
        (("%opr/%", "%opera%"), "Opera"),
        (("%firefox%", "%fxios%"), "Firefox"),
        (("%chrome%", "%crios%"), "Chrome"),
        (("%safari%",), "Safari"),
        (("%curl%", "%python%", "%go-http%", "%wget%", "%httpx%", "%okhttp%"), "Scripts"),
    )
    whens = list(by_class)
    for patterns, label in rules:
        cond = None
        for p in patterns:
            one = ua.like(literal_column(f"'{p}'"))
            cond = one if cond is None else (cond | one)
        whens.append((cond, literal_column(f"'{label}'")))
    whens.append((ua == literal_column("''"), literal_column("'No user agent'")))
    return case(*whens, else_=literal_column("'Other'"))


DIMENSIONS = {
    "paths": lambda: RequestLog.path,
    "hosts": lambda: RequestLog.host,
    "countries": lambda: RequestLog.country_code,
    "referrers": referrer_host_expr,
    "ips": lambda: RequestLog.client_ip,
    "user_agents": lambda: RequestLog.user_agent,
    "browsers": browser_expr,
    "status_codes": lambda: RequestLog.status_code,
    "cache_status": lambda: func.coalesce(RequestLog.cache_status, literal_column("'DYNAMIC'")),
    "methods": lambda: RequestLog.method,
    "traffic": lambda: func.coalesce(RequestLog.client_class, literal_column("'unknown'")),
}
DIMENSION_PATTERN = r"^(paths|hosts|countries|referrers|ips|user_agents|browsers|status_codes|cache_status|methods|traffic|errors)$"


async def top(
    db: AsyncSession,
    range_str: str,
    dimension: str,
    domain_ids: Optional[Sequence[int]] = None,
    limit: int = 10,
    traffic: Optional[str] = None,
    metric: str = "requests",
) -> Dict[str, Any]:
    """Топ значений измерения за период с долей от всех запросов.

    ``metric`` — по чему ранжировать и считать долю: requests, views
    (просмотры страниц) или visitors (уникальные IP). У каждой строки есть
    все три числа. У адресов «посетитель» всегда один, их топ по visitors
    строится по просмотрам; ошибки — всегда по запросам.

    Сырые логи хранятся 30 дней. Для страниц, стран и ошибок дни старше
    добираются из суточных топов; остальные измерения за 90 дней и полгода
    считаются по последним 30 дням (флаг ``partial``). С фильтром трафика
    суточные топы не подходят — в них нет класса, — и все измерения берутся
    за последние 30 дней.
    """
    w = window(range_str)
    floor_raw = raw_floor()
    start = max(w.start, floor_raw)
    partial = w.start < floor_raw
    where = [
        RequestLog.timestamp >= start, RequestLog.timestamp < w.end,
        RequestLog.domain_id.isnot(None),
        *_domain_filter(RequestLog.domain_id, domain_ids),
        *traffic_filter(traffic),
    ]
    if dimension == "errors":
        metric = "requests"
    elif dimension == "ips" and metric == "visitors":
        metric = "views"
    # Суточные топы знают только запросы и не знают класс трафика.
    mergeable = ("paths", "countries", "errors") if not _filtered(traffic) and metric == "requests" else ()
    key_of = {"requests": "requests", "views": "views", "visitors": "visitors"}[metric]

    totals_row = (await db.execute(
        select(
            func.count(RequestLog.id).label("requests"),
            func.count(case((page_view_expr(), 1))).label("views"),
            func.count(func.distinct(RequestLog.client_ip)).label("visitors"),
        ).where(*where)
    )).first()
    total = int(totals_row.requests or 0)
    total_views = int(totals_row.views or 0)
    total_visitors = int(totals_row.visitors or 0)

    items: Dict[Any, Dict[str, Any]] = {}
    if dimension == "errors":
        rows = (await db.execute(
            select(
                RequestLog.status_code.label("status"),
                RequestLog.path.label("path"),
                func.count(RequestLog.id).label("requests"),
                func.max(RequestLog.timestamp).label("last_seen"),
            ).where(*where, RequestLog.status_code >= 400)
            .group_by(RequestLog.status_code, RequestLog.path)
            .order_by(desc("requests")).limit(limit * 3)
        )).all()
        for r in rows:
            items[(r.status, r.path)] = {
                "key": f"{r.status} {r.path}", "status": r.status, "path": r.path,
                "requests": int(r.requests), "bytes": 0, "last_seen": iso(r.last_seen),
            }
    else:
        expr = DIMENSIONS[dimension]()
        filters = list(where)
        if dimension == "referrers":
            filters.append(RequestLog.referer.isnot(None))
            filters.append(RequestLog.referer != "")
        rows = (await db.execute(
            select(
                expr.label("key"),
                func.count(RequestLog.id).label("requests"),
                func.coalesce(func.sum(RequestLog.bytes_sent), 0).label("bytes"),
                func.count(func.distinct(RequestLog.client_ip)).label("visitors"),
                func.count(case((page_view_expr(), 1))).label("views"),
            ).where(*filters)
            .group_by(literal_column("1"))
            .order_by(desc(key_of), desc("requests")).limit(limit * 3)
        )).all()
        for r in rows:
            items[r.key] = {
                "key": r.key, "requests": int(r.requests), "bytes": int(r.bytes),
                "visitors": int(r.visitors), "views": int(r.views),
            }

    if partial and dimension in mergeable:
        total += await _merge_daily_tops(db, dimension, w.start, floor_raw, domain_ids, items)

    base = {"requests": total, "views": total_views, "visitors": total_visitors}[metric]
    ranked = sorted(
        items.values(), key=lambda i: (i.get(key_of, 0), i["requests"]), reverse=True
    )[:limit]
    for item in ranked:
        item["percentage"] = _ratio(item.get(key_of, 0), base)
    if dimension == "traffic":
        for item in ranked:
            item["label"] = tc.LABELS.get(item["key"], "Not classified")
            item["people"] = item["key"] in tc.PEOPLE
    elif dimension == "ips" and ranked:
        await _describe_ips(db, where, ranked)
    return {
        "range": range_str, "dimension": dimension, "total_requests": int(total),
        "total_views": total_views, "total_visitors": total_visitors, "metric": metric,
        "traffic": traffic or "all",
        "partial": partial and dimension not in mergeable,
        "items": ranked,
    }


async def _describe_ips(db: AsyncSession, where: list, items: List[Dict[str, Any]]) -> None:
    """Кто за адресом: сеть (владелец AS) и самый частый класс его запросов."""
    ips = [i["key"] for i in items]
    rows = (await db.execute(
        select(
            RequestLog.client_ip,
            func.mode().within_group(RequestLog.client_class).label("cls"),
        ).where(*where, RequestLog.client_ip.in_(ips)).group_by(RequestLog.client_ip)
    )).all()
    classes = {r.client_ip: r.cls for r in rows}
    for item in items:
        asn, org = ip_networks.lookup(item["key"])
        cls = classes.get(item["key"])
        item.update(
            asn=asn, network=org, traffic_class=cls,
            traffic_label=tc.LABELS.get(cls) if cls else None,
        )


async def _merge_daily_tops(db, dimension, start, end, domain_ids, items) -> int:
    """Добавить к топу суточные своды за дни, сырые логи которых уже удалены."""
    day_from, day_to = start.date(), end.date()
    if dimension == "countries":
        rows = (await db.execute(
            select(GeoStats.country_code.label("key"),
                   func.sum(GeoStats.total_requests).label("requests"),
                   func.sum(GeoStats.total_bytes_sent).label("bytes"))
            .where(GeoStats.day >= day_from, GeoStats.day < day_to,
                   *_domain_filter(GeoStats.domain_id, domain_ids))
            .group_by(GeoStats.country_code)
        )).all()
    elif dimension == "paths":
        rows = (await db.execute(
            select(TopPathsStats.path.label("key"),
                   func.sum(TopPathsStats.total_requests).label("requests"),
                   func.sum(TopPathsStats.total_bytes_sent).label("bytes"))
            .where(TopPathsStats.day >= day_from, TopPathsStats.day < day_to,
                   *_domain_filter(TopPathsStats.domain_id, domain_ids))
            .group_by(TopPathsStats.path)
        )).all()
    else:
        rows = (await db.execute(
            select(ErrorStats.status_code.label("status"), ErrorStats.path.label("path"),
                   func.sum(ErrorStats.error_count).label("requests"))
            .where(ErrorStats.day >= day_from, ErrorStats.day < day_to,
                   *_domain_filter(ErrorStats.domain_id, domain_ids))
            .group_by(ErrorStats.status_code, ErrorStats.path)
        )).all()
    added = 0
    for r in rows:
        if dimension == "errors":
            key = (r.status, r.path)
            item = items.setdefault(key, {"key": f"{r.status} {r.path}", "status": r.status,
                                          "path": r.path, "requests": 0, "bytes": 0})
        else:
            key = r.key
            item = items.setdefault(key, {"key": key, "requests": 0, "bytes": 0})
            item["bytes"] += int(r.bytes or 0)
        item["requests"] += int(r.requests or 0)
        added += int(r.requests or 0)
    # Итог дней без сырых логов — из суточного свода, иначе доли завышены.
    total_old = (await db.execute(
        select(func.coalesce(func.sum(DailyStats.total_requests), 0)).where(
            DailyStats.day >= day_from, DailyStats.day < day_to,
            *_domain_filter(DailyStats.domain_id, domain_ids),
        )
    )).scalar() or 0
    return int(total_old or added)


# --- события безопасности --------------------------------------------------


async def security_events(
    db: AsyncSession,
    range_str: str,
    domain_ids: Optional[Sequence[int]] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Последние заблокированные и ограниченные запросы (WAF и 429)."""
    w = window(range_str)
    rows = (await db.execute(
        select(
            RequestLog.timestamp, RequestLog.domain_id, RequestLog.host,
            RequestLog.client_ip, RequestLog.country_code, RequestLog.method,
            RequestLog.path, RequestLog.status_code, RequestLog.waf_status,
            RequestLog.waf_rule_id, RequestLog.user_agent,
        ).where(
            RequestLog.timestamp >= max(w.start, raw_floor()), RequestLog.timestamp < w.end,
            RequestLog.domain_id.isnot(None),
            *_domain_filter(RequestLog.domain_id, domain_ids),
            (RequestLog.waf_status.in_(("blocked", "challenged"))) | (RequestLog.status_code == 429),
        ).order_by(RequestLog.timestamp.desc()).limit(limit)
    )).all()
    return [
        {
            "timestamp": iso(r.timestamp), "domain_id": r.domain_id, "host": r.host,
            "client_ip": r.client_ip, "country_code": r.country_code, "method": r.method,
            "path": r.path, "status": r.status_code,
            "action": r.waf_status or ("rate_limited" if r.status_code == 429 else None),
            "rule_id": r.waf_rule_id, "user_agent": r.user_agent,
        }
        for r in rows
    ]
