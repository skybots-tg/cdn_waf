"""Аналитика одного домена: итоги, ряды, топы, события безопасности, логи, выгрузка.

Все цифры считает ``app.services.analytics_query`` — тот же слой, что у общей
аналитики, поэтому домен и сводка по всем доменам сходятся. Старые поля
ответов сохранены: на них могут опираться внешние клиенты с API-токеном.
"""
import csv
import io
import json
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_domain_for_user, visible_domain_ids
from app.core.database import get_db
from app.core.security import get_current_active_user
from app.models.domain import Domain
from app.models.log import RequestLog
from app.models.user import User
from app.services import analytics_query as aq

router = APIRouter()


@router.get("/domains/{domain_id}/stats/basic")
@router.get("/domains/{domain_id}/stats/overview")
async def get_domain_overview(
    domain_id: int,
    range: str = Query("24h", regex=aq.RANGE_PATTERN),
    traffic: str = Query("all", regex=aq.TRAFFIC_PATTERN),
    domain: Domain = Depends(get_domain_for_user),
    db: AsyncSession = Depends(get_db),
):
    """Итоги периода: запросы, трафик, кэш, угрозы, посетители, время ответа.

    ``traffic``: all — всё, people — только люди, bots — только боты.
    """
    return await aq.overview(db, range, [domain.id], traffic)


@router.get("/domains/{domain_id}/stats/timeseries")
async def get_domain_timeseries(
    domain_id: int,
    range: str = Query("24h", regex=aq.RANGE_PATTERN),
    metric: str = Query("requests", regex="^(" + "|".join(aq.SERIES) + ")$"),
    traffic: str = Query("all", regex=aq.TRAFFIC_PATTERN),
    domain: Domain = Depends(get_domain_for_user),
    db: AsyncSession = Depends(get_db),
):
    return await aq.timeseries(db, range, [domain.id], metric, traffic)


@router.get("/domains/{domain_id}/stats/top")
async def get_domain_top(
    domain_id: int,
    dimension: str = Query("paths", regex=aq.DIMENSION_PATTERN),
    range: str = Query("24h", regex=aq.RANGE_PATTERN),
    limit: int = Query(10, ge=1, le=100),
    traffic: str = Query("all", regex=aq.TRAFFIC_PATTERN),
    domain: Domain = Depends(get_domain_for_user),
    db: AsyncSession = Depends(get_db),
):
    """Топ по измерению: страницы, хосты, страны, источники, IP, браузеры, классы трафика…"""
    return await aq.top(db, range, dimension, [domain.id], limit, traffic)


@router.get("/domains/{domain_id}/stats/top_paths")
async def get_domain_top_paths(
    domain_id: int,
    range: str = Query("24h", regex=aq.RANGE_PATTERN),
    limit: int = Query(10, ge=1, le=100),
    domain: Domain = Depends(get_domain_for_user),
    db: AsyncSession = Depends(get_db),
):
    result = await aq.top(db, range, "paths", [domain.id], limit)
    return [
        {"path": i["key"], "requests": i["requests"], "bytes": i["bytes"],
         "percentage": i["percentage"]}
        for i in result["items"]
    ]


@router.get("/domains/{domain_id}/stats/errors")
async def get_domain_errors(
    domain_id: int,
    range: str = Query("24h", regex=aq.RANGE_PATTERN),
    limit: int = Query(20, ge=1, le=100),
    domain: Domain = Depends(get_domain_for_user),
    db: AsyncSession = Depends(get_db),
):
    result = await aq.top(db, range, "errors", [domain.id], limit)
    return [
        {"status_code": i["status"], "path": i["path"], "count": i["requests"],
         "percentage": i["percentage"], "last_seen": i.get("last_seen")}
        for i in result["items"]
    ]


@router.get("/domains/{domain_id}/stats/geo")
async def get_domain_geo_stats(
    domain_id: int,
    range: str = Query("24h", regex=aq.RANGE_PATTERN),
    limit: int = Query(10, ge=1, le=250),
    domain: Domain = Depends(get_domain_for_user),
    db: AsyncSession = Depends(get_db),
):
    result = await aq.top(db, range, "countries", [domain.id], limit)
    return [
        {"country": i["key"],
         "requests": i["requests"], "visitors": i.get("visitors", 0),
         "bytes": i["bytes"], "percentage": i["percentage"]}
        for i in result["items"]
    ]


@router.get("/domains/{domain_id}/stats/security")
async def get_domain_security_events(
    domain_id: int,
    range: str = Query("24h", regex=aq.RANGE_PATTERN),
    limit: int = Query(50, ge=1, le=500),
    domain: Domain = Depends(get_domain_for_user),
    db: AsyncSession = Depends(get_db),
):
    """Заблокированные WAF и ограниченные по частоте (429) запросы."""
    return await aq.security_events(db, range, [domain.id], limit)


@router.get("/domains/{domain_id}/logs")
async def get_domain_logs(
    response: Response,
    domain_id: int,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    status: Optional[int] = None,
    status_class: Optional[str] = Query(None, regex="^[1-5]xx$"),
    method: Optional[str] = None,
    range: Optional[str] = Query(None, regex=aq.RANGE_PATTERN),
    host: Optional[str] = None,
    path: Optional[str] = Query(None, max_length=512),
    ip: Optional[str] = Query(None, max_length=45),
    cache_status: Optional[str] = Query(None, max_length=20),
    country: Optional[str] = Query(None, max_length=2),
    traffic: Optional[str] = Query(None, regex=aq.TRAFFIC_PATTERN),
    domain: Domain = Depends(get_domain_for_user),
    db: AsyncSession = Depends(get_db),
):
    """Сырые логи домена (хранятся 30 дней), новые сверху.

    Всего строк по фильтру — в заголовке ``X-Total-Count``: тело осталось
    списком, как было, чтобы не сломать клиентов API.
    """
    where = [RequestLog.domain_id == domain.id]
    if range:
        where.append(RequestLog.timestamp >= aq.window(range).start)
    if status:
        where.append(RequestLog.status_code == status)
    if status_class:
        base = int(status_class[0]) * 100
        where.append(RequestLog.status_code.between(base, base + 99))
    if method:
        where.append(RequestLog.method == method.upper())
    if host:
        where.append(RequestLog.host == host.lower())
    if path:
        where.append(RequestLog.path.ilike(f"%{_escape_like(path)}%", escape="\\"))
    if ip:
        where.append(RequestLog.client_ip == ip)
    if cache_status:
        if cache_status.upper() == "DYNAMIC":
            where.append(RequestLog.cache_status.is_(None))
        else:
            where.append(RequestLog.cache_status == cache_status.upper())
    if country:
        where.append(RequestLog.country_code == country.upper())
    where.extend(aq.traffic_filter(traffic))

    total = (await db.execute(select(func.count(RequestLog.id)).where(*where))).scalar() or 0
    response.headers["X-Total-Count"] = str(total)
    rows = (await db.execute(
        select(RequestLog).where(*where)
        .order_by(RequestLog.timestamp.desc(), RequestLog.id.desc())
        .offset(offset).limit(limit)
    )).scalars().all()
    return [_log_dict(log) for log in rows]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _log_dict(log: RequestLog) -> dict:
    return {
        "id": log.id,
        "timestamp": aq.iso(log.timestamp),
        "host": log.host,
        "method": log.method,
        "path": log.path,
        "query_string": log.query_string,
        "status": log.status_code,
        "client_ip": log.client_ip,
        "bytes_sent": log.bytes_sent,
        "cache_status": log.cache_status,
        "country_code": log.country_code,
        "request_time": log.request_time,
        "referer": log.referer,
        "waf_status": log.waf_status,
        "waf_rule_id": log.waf_rule_id,
        "user_agent": log.user_agent,
        "asn": log.asn,
        "client_class": log.client_class,
        "traffic_label": aq.tc.LABELS.get(log.client_class) if log.client_class else None,
    }


@router.get("/domains/{domain_id}/export")
async def export_domain_analytics(
    domain_id: int,
    range: str = Query("24h", regex=aq.RANGE_PATTERN),
    format: str = Query("csv", regex="^(csv|json)$"),
    traffic: str = Query("all", regex=aq.TRAFFIC_PATTERN),
    domain: Domain = Depends(get_domain_for_user),
    db: AsyncSession = Depends(get_db),
):
    return await _export(db, range, format, [domain.id], _filename(domain.name, range, traffic), traffic)


@router.get("/export/global")
async def export_global_analytics(
    range: str = Query("24h", regex=aq.RANGE_PATTERN),
    format: str = Query("csv", regex="^(csv|json)$"),
    traffic: str = Query("all", regex=aq.TRAFFIC_PATTERN),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    domain_ids = await visible_domain_ids(current_user, db)
    return await _export(db, range, format, domain_ids, _filename("global", range, traffic), traffic)


def _filename(name: str, range_str: str, traffic: str) -> str:
    suffix = "" if traffic == "all" else f"_{traffic}"
    return f"{name}_analytics_{range_str}{suffix}"


async def _export(db, range_str, fmt, domain_ids, filename, traffic="all"):
    """Выгрузка: итоги, ряд по шагам и основные топы."""
    overview = await aq.overview(db, range_str, domain_ids, traffic)
    series = await aq.timeseries(db, range_str, domain_ids, traffic=traffic)
    tops = {
        dim: (await aq.top(db, range_str, dim, domain_ids, 20, traffic))["items"]
        for dim in ("paths", "countries", "referrers", "status_codes", "browsers", "traffic")
    }
    if fmt == "json":
        body = json.dumps(
            {"overview": overview, "timeseries": series, "top": tops},
            ensure_ascii=False, default=str, indent=2,
        )
        return StreamingResponse(
            iter([body]), media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}.json"},
        )

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Metric", "Value"])
    for key in ("total_requests", "cached_requests", "total_bandwidth", "cached_bandwidth",
                "cache_hit_ratio", "unique_visitors", "threats_blocked", "rate_limited",
                "status_2xx", "status_3xx", "status_4xx", "status_5xx",
                "avg_response_time", "p50_response_time", "p95_response_time"):
        writer.writerow([key, overview.get(key)])
    writer.writerow([])
    names = list(series["series"])
    writer.writerow(["Time (UTC)"] + names)
    for i, ts in enumerate(series["timestamps"]):
        writer.writerow([ts] + [series["series"][n][i] for n in names])
    for dim, items in tops.items():
        writer.writerow([])
        writer.writerow([f"Top {dim}", "Requests", "Percentage"])
        for item in items:
            writer.writerow([item["key"], item["requests"], item["percentage"]])
    out.seek(0)
    return StreamingResponse(
        iter([out.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}.csv"},
    )
