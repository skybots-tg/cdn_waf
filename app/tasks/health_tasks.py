"""Periodic health check tasks: origins, edge nodes, DNS nodes"""
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select

from app.tasks import celery_app
from app.tasks.utils import create_task_db_session

logger = logging.getLogger(__name__)

PROLONGED_OUTAGE_MINUTES = 5
EDGE_HTTP_TIMEOUT = 5
EDGE_STALE_HEARTBEAT_MINUTES = 5
EDGE_FAILURE_THRESHOLD = 3
DNS_HTTP_TIMEOUT = 5
DNS_FAILURE_THRESHOLD = 3


@celery_app.task(name="app.tasks.health.check_origins_health")
def check_origins_health():
    """
    Every-minute origin health check.

    1. HTTP-ping every enabled origin.
    2. On failure — increment consecutive_failures, set disabled_until (cooldown).
    3. On recovery — reset counters, remove cooldown.
    4. If ALL origins for a domain are down — force-keep one with least failures
       and send CRITICAL alert tagging the user.
    5. Send WARNING alerts on individual origin failures.
    6. Send CRITICAL alert if outage persists >5 minutes.
    7. Bump edge config_version so nodes pull fresh upstream list.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_check_origins_health_async())
    finally:
        loop.close()


async def _check_origins_health_async():  # noqa: C901
    from app.models.origin import Origin
    from app.models.domain import Domain
    from app.services.origin_service import OriginService
    from app.services.alert_service import AlertService

    engine, SessionLocal = create_task_db_session()
    try:
        async with SessionLocal() as db:
            result = await db.execute(
                select(Origin).where(
                    Origin.enabled == True,
                    Origin.health_check_enabled == True,
                )
            )
            origins = list(result.scalars().all())
            if not origins:
                return {"status": "ok", "checked": 0}

            domain_ids = {o.domain_id for o in origins}
            domains_result = await db.execute(
                select(Domain).where(Domain.id.in_(domain_ids))
            )
            domain_map = {d.id: d for d in domains_result.scalars().all()}

            checked = 0
            any_state_changed = False
            check_results: list[dict] = []

            for origin in origins:
                try:
                    res = await OriginService.check_health(db, origin.id)
                    checked += 1
                    res["origin_id"] = origin.id
                    res["origin_name"] = origin.name
                    res["origin_host"] = origin.origin_host
                    res["domain_id"] = origin.domain_id
                    check_results.append(res)
                    if res.get("changed"):
                        any_state_changed = True
                except Exception as e:
                    logger.error("Health check error for origin %s: %s", origin.id, e)

            by_domain: dict[int, list[dict]] = defaultdict(list)
            for cr in check_results:
                by_domain[cr["domain_id"]].append(cr)

            for domain_id, results in by_domain.items():
                domain = domain_map.get(domain_id)
                domain_name = domain.name if domain else f"domain#{domain_id}"

                for cr in results:
                    if cr.get("changed") and not cr["is_healthy"]:
                        await AlertService.origin_down(
                            origin_name=cr["origin_name"],
                            origin_host=cr["origin_host"],
                            domain_name=domain_name,
                            consecutive_failures=cr["consecutive_failures"],
                        )

                    if cr.get("changed") and cr["is_healthy"]:
                        await AlertService.origin_recovered(
                            origin_name=cr["origin_name"],
                            origin_host=cr["origin_host"],
                            domain_name=domain_name,
                        )

                await _failsafe_keep_one(db, domain_id, domain_name, AlertService)

                unhealthy_count = sum(1 for r in results if not r["is_healthy"])
                if unhealthy_count > 0:
                    await _check_prolonged_outage(
                        db, domain_id, domain_name, unhealthy_count,
                        len(results), AlertService,
                    )

            if any_state_changed:
                await _bump_all_edge_configs(db)

            return {"status": "ok", "checked": checked}
    finally:
        await engine.dispose()


async def _failsafe_keep_one(db, domain_id: int, domain_name: str, alert_svc):
    """If all enabled origins for a domain are unhealthy, force-keep one."""
    from app.models.origin import Origin

    result = await db.execute(
        select(Origin).where(
            Origin.domain_id == domain_id,
            Origin.enabled == True,
        )
    )
    all_origins = list(result.scalars().all())
    if not all_origins:
        return

    if all(not o.is_healthy for o in all_origins):
        best = min(all_origins, key=lambda o: (o.consecutive_failures, o.id))
        best.is_healthy = True
        best.health_status = "healthy"
        best.disabled_until = None
        await db.commit()

        await alert_svc.all_origins_down(
            domain_name=domain_name,
            kept_origin=f"{best.name} ({best.origin_host})",
        )
        logger.critical(
            "All origins down for %s — kept %s as last-resort fallback",
            domain_name, best.name,
        )


async def _check_prolonged_outage(
    db, domain_id: int, domain_name: str,
    unhealthy_count: int, total_count: int, alert_svc,
):
    """Send critical alert if any origin has been failing for >5 minutes."""
    from app.models.origin import Origin

    result = await db.execute(
        select(Origin).where(
            Origin.domain_id == domain_id,
            Origin.enabled == True,
            Origin.is_healthy == False,
        )
    )
    unhealthy_origins = list(result.scalars().all())
    now = datetime.utcnow()

    for origin in unhealthy_origins:
        if not origin.last_health_check:
            continue
        failure_start = origin.last_health_check - timedelta(
            seconds=60 * max((origin.consecutive_failures or 1) - 1, 0)
        )
        minutes_down = int((now - failure_start).total_seconds() / 60)
        if minutes_down >= PROLONGED_OUTAGE_MINUTES and minutes_down % PROLONGED_OUTAGE_MINUTES == 0:
            await alert_svc.prolonged_outage(
                domain_name=domain_name,
                duration_minutes=minutes_down,
                unhealthy_origins=unhealthy_count,
                total_origins=total_count,
            )
            break


async def _bump_all_edge_configs(db):
    """Bump config_version on all enabled edge nodes."""
    from app.models.edge_node import EdgeNode

    result = await db.execute(select(EdgeNode).where(EdgeNode.enabled == True))
    nodes = list(result.scalars().all())
    for node in nodes:
        node.config_version = (node.config_version or 0) + 1
    await db.commit()
    logger.info("Bumped config_version for %d edge nodes after health state change", len(nodes))


# ---------------------------------------------------------------------------
# Edge node health check
# ---------------------------------------------------------------------------

@celery_app.task(name="app.tasks.health.check_edge_nodes_health", soft_time_limit=90, time_limit=120)
def check_edge_nodes_health():
    """Check all enabled edge nodes: HTTP probe + stale heartbeat."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_check_edge_nodes_health_async())
    finally:
        loop.close()


async def _check_edge_nodes_health_async():
    from app.models.edge_node import EdgeNode
    from app.services.alert_service import AlertService
    from app.core.redis import redis_client
    from app.tasks.dns_tasks import sync_dns_nodes

    await redis_client.connect()
    engine, SessionLocal = create_task_db_session()
    try:
        async with SessionLocal() as db:
            result = await db.execute(
                select(EdgeNode).where(EdgeNode.enabled == True)
            )
            nodes = list(result.scalars().all())
            if not nodes:
                return {"status": "ok", "checked": 0}

            checked = 0
            disabled_any = False

            for node in nodes:
                checked += 1
                healthy = await _probe_edge_node(node)
                redis_key = f"edge:failures:{node.id}"

                if healthy:
                    old_failures = int(await redis_client.get(redis_key) or 0)
                    if old_failures > 0:
                        await redis_client.delete(redis_key)
                    if node.status == "offline":
                        node.status = "online"
                        await db.commit()
                        logger.info("Edge node %s (%s) recovered", node.name, node.ip_address)
                        await AlertService.edge_node_recovered(node.name, node.ip_address)
                else:
                    failures = int(await redis_client.get(redis_key) or 0) + 1
                    await redis_client.set(redis_key, str(failures), expire=600)

                    reason = _edge_failure_reason(node)
                    logger.warning(
                        "Edge node %s (%s) failing (%d/%d): %s",
                        node.name, node.ip_address, failures, EDGE_FAILURE_THRESHOLD, reason,
                    )
                    await AlertService.edge_node_down(node.name, node.ip_address, reason)

                    if failures >= EDGE_FAILURE_THRESHOLD:
                        node.enabled = False
                        node.status = "offline"
                        await db.commit()
                        disabled_any = True
                        await redis_client.delete(redis_key)
                        await redis_client.set(
                            f"edge:auto_disabled:{node.id}", "1", expire=86400,
                        )
                        logger.critical(
                            "Edge node %s (%s) auto-disabled after %d failures",
                            node.name, node.ip_address, failures,
                        )
                        await AlertService.edge_node_disabled(
                            node.name, node.ip_address,
                            f"{failures} неудачных проверок подряд ({reason})",
                        )

            if disabled_any:
                sync_dns_nodes.delay()
                logger.info("Triggered DNS sync after edge node auto-disable")

            await _check_auto_disabled_recovery(db, redis_client, AlertService)

            return {"status": "ok", "checked": checked, "disabled_any": disabled_any}
    finally:
        await engine.dispose()
        await redis_client.disconnect()


async def _probe_edge_node(node) -> bool:
    """HTTP probe on port 80 + stale heartbeat check."""
    now = datetime.utcnow()

    if node.last_heartbeat:
        stale = (now - node.last_heartbeat).total_seconds() > EDGE_STALE_HEARTBEAT_MINUTES * 60
    else:
        stale = True

    http_ok = False
    try:
        async with httpx.AsyncClient(timeout=EDGE_HTTP_TIMEOUT) as client:
            resp = await client.get(f"http://{node.ip_address}", follow_redirects=False)
            http_ok = resp.status_code < 600
    except Exception:
        http_ok = False

    return http_ok and not stale


def _edge_failure_reason(node) -> str:
    parts = []
    now = datetime.utcnow()
    if node.last_heartbeat:
        age = int((now - node.last_heartbeat).total_seconds())
        if age > EDGE_STALE_HEARTBEAT_MINUTES * 60:
            parts.append(f"heartbeat устарел ({age}s)")
    else:
        parts.append("heartbeat отсутствует")
    parts.append("HTTP check failed")
    return "; ".join(parts)


async def _check_auto_disabled_recovery(db, redis_client, alert_svc):
    """Re-enable nodes that were auto-disabled and are now responding.

    Only touches nodes marked with `edge:auto_disabled:{id}` in Redis.
    Manually disabled nodes are never probed.
    """
    from app.models.edge_node import EdgeNode
    from app.tasks.dns_tasks import sync_dns_nodes

    result = await db.execute(
        select(EdgeNode).where(
            EdgeNode.enabled == False,
            EdgeNode.status == "offline",
        )
    )
    disabled_nodes = list(result.scalars().all())
    re_enabled_any = False

    for node in disabled_nodes:
        marker = await redis_client.get(f"edge:auto_disabled:{node.id}")
        if not marker:
            continue

        try:
            async with httpx.AsyncClient(timeout=EDGE_HTTP_TIMEOUT) as client:
                resp = await client.get(
                    f"http://{node.ip_address}", follow_redirects=False,
                )
                if resp.status_code < 600:
                    node.enabled = True
                    node.status = "online"
                    await db.commit()
                    await redis_client.delete(f"edge:auto_disabled:{node.id}")
                    re_enabled_any = True
                    logger.info(
                        "Auto-disabled edge node %s (%s) recovered — re-enabled",
                        node.name, node.ip_address,
                    )
                    await alert_svc.edge_node_recovered(node.name, node.ip_address)
        except Exception:
            pass

    if re_enabled_any:
        sync_dns_nodes.delay()
        logger.info("Triggered DNS sync after auto-disabled edge node recovery")


# ---------------------------------------------------------------------------
# DNS node health check
# ---------------------------------------------------------------------------

@celery_app.task(name="app.tasks.health.check_dns_nodes_health", soft_time_limit=60, time_limit=90)
def check_dns_nodes_health():
    """Check all enabled DNS nodes: HTTP probe to management API."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_check_dns_nodes_health_async())
    finally:
        loop.close()


async def _check_dns_nodes_health_async():
    from app.models.dns_node import DNSNode
    from app.services.alert_service import AlertService
    from app.core.redis import redis_client

    await redis_client.connect()
    engine, SessionLocal = create_task_db_session()
    try:
        async with SessionLocal() as db:
            result = await db.execute(
                select(DNSNode).where(DNSNode.enabled == True)
            )
            nodes = list(result.scalars().all())
            if not nodes:
                return {"status": "ok", "checked": 0}

            checked = 0
            for node in nodes:
                checked += 1
                healthy = await _probe_dns_node(node)
                redis_key = f"dns:failures:{node.id}"

                if healthy:
                    old_failures = int(await redis_client.get(redis_key) or 0)
                    if old_failures > 0:
                        await redis_client.delete(redis_key)
                    if node.status == "offline":
                        node.status = "online"
                        await db.commit()
                        logger.info("DNS node %s (%s) recovered", node.name, node.ip_address)
                        await AlertService.dns_node_recovered(node.name, node.ip_address)
                else:
                    failures = int(await redis_client.get(redis_key) or 0) + 1
                    await redis_client.set(redis_key, str(failures), expire=600)

                    logger.warning(
                        "DNS node %s (%s) failing (%d/%d)",
                        node.name, node.ip_address, failures, DNS_FAILURE_THRESHOLD,
                    )

                    if failures >= DNS_FAILURE_THRESHOLD:
                        node.status = "offline"
                        await db.commit()
                        await AlertService.dns_node_down(node.name, node.ip_address)
                        logger.critical(
                            "DNS node %s (%s) marked offline after %d failures",
                            node.name, node.ip_address, failures,
                        )

            return {"status": "ok", "checked": checked}
    finally:
        await engine.dispose()
        await redis_client.disconnect()


async def _probe_dns_node(node) -> bool:
    """HTTP probe to the DNS node management API."""
    try:
        async with httpx.AsyncClient(timeout=DNS_HTTP_TIMEOUT) as client:
            resp = await client.get(f"http://{node.ip_address}:8000/health")
            return resp.status_code == 200
    except Exception:
        return False
