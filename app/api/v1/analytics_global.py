"""Общая аналитика: сводка по доменам, ряды, топы, ноды, события безопасности.

Считает тот же слой, что и аналитика домена (``analytics_query``). Видимость —
``visible_domain_ids``: суперпользователь видит всё, остальные — домены своих
организаций. До 23.09.2026 сводка была только для суперпользователя, а у
остальных экраны показывали нули из-за 403.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import visible_domain_ids
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_active_user
from app.models.domain import Domain
from app.models.edge_node import EdgeNode
from app.models.user import User
from app.services import analytics_query as aq

router = APIRouter()


@router.get("/stats/global")
async def get_global_stats(
    range: str = Query("24h", regex=aq.RANGE_PATTERN),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Итоги по всем видимым доменам с изменением к прошлому периоду."""
    domain_ids = await visible_domain_ids(current_user, db)
    data = await aq.overview(db, range, domain_ids)
    data["total_domains"] = len(await _domains(db, domain_ids))
    return data


@router.get("/stats/global/timeseries")
async def get_global_timeseries(
    range: str = Query("24h", regex=aq.RANGE_PATTERN),
    metric: str = Query("requests", regex="^(" + "|".join(aq.SERIES) + ")$"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    domain_ids = await visible_domain_ids(current_user, db)
    return await aq.timeseries(db, range, domain_ids, metric)


@router.get("/stats/top")
async def get_global_top(
    dimension: str = Query("paths", regex=aq.DIMENSION_PATTERN),
    range: str = Query("24h", regex=aq.RANGE_PATTERN),
    limit: int = Query(10, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    domain_ids = await visible_domain_ids(current_user, db)
    return await aq.top(db, range, dimension, domain_ids, limit)


@router.get("/stats/domains")
async def get_domains_stats(
    range: str = Query("24h", regex=aq.RANGE_PATTERN),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Таблица доменов: трафик, кэш, угрозы и ошибки за период."""
    domain_ids = await visible_domain_ids(current_user, db)
    domains = await _domains(db, domain_ids)
    by_domain = await aq.totals(db, aq.window(range), domain_ids, group_by="domain")
    rows = []
    for domain in domains:
        m = by_domain.get(domain.id, aq.Metrics()).as_dict()
        rows.append({
            "id": domain.id,
            "name": domain.name,
            "status": domain.status.value,
            "requests": m["total_requests"],
            "bandwidth": m["total_bandwidth"],
            "cached_bandwidth": m["cached_bandwidth"],
            "cache_ratio": m["cache_hit_ratio"],
            "cacheable_ratio": m["cacheable_hit_ratio"],
            "cache_hits": m["cache_hits"],
            "cache_misses": m["cache_misses"],
            "threats": m["threats_blocked"],
            "errors": m["status_4xx"] + m["status_5xx"],
            "error_rate": m["error_rate"],
            "avg_response_time": m["avg_response_time"],
        })
    rows.sort(key=lambda r: r["requests"], reverse=True)
    return rows


@router.get("/stats/geo")
async def get_geo_stats(
    range: str = Query("24h", regex=aq.RANGE_PATTERN),
    limit: int = Query(10, ge=1, le=250),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    domain_ids = await visible_domain_ids(current_user, db)
    result = await aq.top(db, range, "countries", domain_ids, limit)
    return [
        {"country": i["key"], "requests": i["requests"], "visitors": i.get("visitors", 0),
         "bytes": i["bytes"], "percentage": i["percentage"]}
        for i in result["items"]
    ]


@router.get("/stats/security")
async def get_global_security_events(
    range: str = Query("24h", regex=aq.RANGE_PATTERN),
    limit: int = Query(50, ge=1, le=500),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    domain_ids = await visible_domain_ids(current_user, db)
    events = await aq.security_events(db, range, domain_ids, limit)
    names = {d.id: d.name for d in await _domains(db, domain_ids)}
    for event in events:
        event["domain"] = names.get(event["domain_id"])
    return events


@router.get("/stats/edge-nodes")
async def get_edge_nodes_stats(
    range: str = Query("24h", regex=aq.RANGE_PATTERN),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Ноды: трафик и время ответа за период плюс состояние из heartbeat.

    Раньше брался «последний час» из почасового свода, а текущий час туда
    ещё не попадал — у всех нод всегда был 0.
    """
    domain_ids = await visible_domain_ids(current_user, db)
    w = aq.window(range)
    by_node = await aq.totals(db, w, domain_ids, group_by="node")
    seconds = max((w.end - w.start).total_seconds(), 1)
    nodes = (await db.execute(select(EdgeNode).order_by(EdgeNode.id))).scalars().all()
    # Резервные ноды (BACKUP_EDGE_IPS) DNS отдаёт, только когда основных нет.
    backups = {ip.strip() for ip in settings.BACKUP_EDGE_IPS.split(",") if ip.strip()}
    rows = []
    for node in nodes:
        m = by_node.get(node.id, aq.Metrics()).as_dict()
        rows.append({
            "id": node.id,
            "name": node.name,
            "ip_address": node.ip_address,
            "location": node.location_code,
            "city": node.city,
            "status": node.status,
            "enabled": node.enabled,
            "backup": node.ip_address in backups,
            "requests": m["total_requests"],
            "rps": round(m["total_requests"] / seconds, 2),
            "bandwidth": m["total_bandwidth"],
            "cache_ratio": m["cache_hit_ratio"],
            "error_rate": m["error_rate"],
            "avg_latency": m["avg_response_time"],
            "cpu_usage": node.cpu_usage or 0,
            "memory_usage": node.memory_usage or 0,
            "disk_usage": node.disk_usage or 0,
            "last_heartbeat": aq.iso(node.last_heartbeat),
            "heartbeat_age": (
                int((datetime.utcnow() - node.last_heartbeat).total_seconds())
                if node.last_heartbeat else None
            ),
        })
    return rows


async def _domains(db: AsyncSession, domain_ids):
    q = select(Domain).order_by(Domain.name)
    if domain_ids is not None:
        q = q.where(Domain.id.in_(domain_ids or [-1]))
    return list((await db.execute(q)).scalars().all())
