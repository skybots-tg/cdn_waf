"""Internal API — log ingestion, ACME challenges, and file download for edge nodes."""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import String, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.core.redis import redis_client
from app.models.edge_node import EdgeNode
from app.models.domain import Domain
from app.models.log import RequestLog

logger = logging.getLogger(__name__)

router = APIRouter()


def _as_int(value, default=None):
    """Целое из того, что прислала нода, или default.

    Nginx подставляет в лог пустую строку или дефис там, где переменной нет:
    так в status и waf_rule_id приходило "", и вставка партии логов
    падала целиком с 'str' object cannot be interpreted as an integer.
    Партия — это сотни строк от всех нод сразу, поэтому одна пустая переменная
    роняла приём логов у всех.
    """
    if value is None or value == "" or value == "-":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# Максимальные длины строковых колонок request_logs. Nginx присылает path,
# query_string, referer и user_agent любой длины (сканеры шлют URL на десятки
# килобайт), а колонки — VARCHAR(2048)/VARCHAR(512). Одна такая строка роняла
# INSERT всей партии (сотни записей от всех нод), нода повторяла отправку,
# а PostgreSQL на каждую попытку писал в лог полный текст запроса — ~2.5 ГБ/сутки.
_STR_LIMITS: Dict[str, int] = {
    col.name: col.type.length
    for col in RequestLog.__table__.columns
    if isinstance(col.type, String) and col.type.length
}


def _fit(value: Any, column: str) -> Optional[str]:
    """Приводит значение к строке и обрезает по длине колонки request_logs."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    limit = _STR_LIMITS.get(column)
    if limit and len(value) > limit:
        return value[:limit]
    return value


# verify_edge_node is defined in internal.py which imports us at the bottom,
# so by the time our endpoints are called, the function is fully available.
from app.api.internal import verify_edge_node


@router.post("/logs")
async def receive_logs(
    logs: List[Dict[str, Any]],
    node: EdgeNode = Depends(verify_edge_node),
    db: AsyncSession = Depends(get_db)
):
    """Receive logs from edge node"""
    if not logs:
        return {"status": "ok", "received": 0}

    domain_names = list(set(log.get("domain") for log in logs if log.get("domain")))
    domains_map = {}

    if domain_names:
        domains_result = await db.execute(
            select(Domain).where(Domain.name.in_(domain_names))
        )
        domains_map = {d.name: d.id for d in domains_result.scalars().all()}

    log_entries = []
    for log_data in logs:
        domain_name = log_data.get("domain")
        domain_id = domains_map.get(domain_name)

        timestamp_str = log_data.get("timestamp")
        if timestamp_str:
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                if timestamp.tzinfo is not None:
                    timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
            except ValueError:
                timestamp = datetime.utcnow()
        else:
            timestamp = datetime.utcnow()

        raw_request_time = log_data.get("request_time")
        try:
            request_time_ms = int(float(raw_request_time) * 1000) if raw_request_time is not None else None
        except (ValueError, TypeError):
            request_time_ms = None

        raw_path = log_data.get("path") or "/"
        if "?" in raw_path:
            path, query_string = raw_path.split("?", 1)
        else:
            path, query_string = raw_path, None

        cache_status = log_data.get("cache_status")
        if cache_status in ("", "-", None):
            cache_status = None

        entry = RequestLog(
            timestamp=timestamp,
            domain_id=domain_id,
            edge_node_id=node.id,
            method=_fit(log_data.get("method"), "method"),
            path=_fit(path, "path"),
            query_string=_fit(query_string, "query_string"),
            status_code=_as_int(log_data.get("status")),
            bytes_sent=_as_int(log_data.get("bytes_sent"), 0),
            client_ip=_fit(log_data.get("client_ip"), "client_ip"),
            cache_status=_fit(cache_status, "cache_status"),
            user_agent=_fit(log_data.get("user_agent"), "user_agent"),
            referer=_fit(log_data.get("referer"), "referer"),
            request_time=request_time_ms,
            country_code=_fit(log_data.get("country_code") or None, "country_code"),
            waf_status=_fit(log_data.get("waf_status") or None, "waf_status"),
            waf_rule_id=_as_int(log_data.get("waf_rule_id")),
        )
        log_entries.append(entry)

    if log_entries:
        db.add_all(log_entries)
        await db.commit()

    return {
        "status": "ok",
        "received": len(logs),
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/acme-challenge/{token}", response_class=PlainTextResponse)
async def get_acme_challenge(
    token: str,
    node: EdgeNode = Depends(verify_edge_node),
):
    """Get ACME challenge response for edge nodes"""
    logger.info(f"ACME challenge request from edge node {node.name} for token: {token[:20]}...")

    validation = None
    if redis_client:
        key = f"acme:challenge:{token}"
        validation = await redis_client.get(key)
        logger.info(f"Redis lookup for key: {key}, found: {validation is not None}")

    if not validation:
        if redis_client and settings.DEBUG:
            try:
                all_keys = await redis_client.keys("acme:challenge:*")
                logger.warning(f"Challenge not found. Available keys: {all_keys}")
            except Exception as e:
                logger.warning(f"Could not list ACME keys: {e}")

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Challenge not found",
        )

    return PlainTextResponse(content=validation)


@router.get("/download/edge_config_updater.py", response_class=PlainTextResponse)
async def download_edge_config_updater(
    node: EdgeNode = Depends(verify_edge_node),
):
    """Download latest edge_config_updater.py for edge nodes"""
    from pathlib import Path

    logger.info(f"Edge node {node.name} requesting edge_config_updater.py download")

    updater_path = Path(__file__).parent.parent.parent / "edge_node" / "edge_config_updater.py"
    if not updater_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="edge_config_updater.py not found",
        )

    with open(updater_path, "r", encoding="utf-8") as f:
        content = f.read()

    logger.info(f"Sending edge_config_updater.py ({len(content)} bytes)")
    return PlainTextResponse(content=content)
