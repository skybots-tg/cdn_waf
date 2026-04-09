"""Periodic origin health check task with alerting and failsafe logic"""
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select

from app.tasks import celery_app
from app.tasks.utils import create_task_db_session

logger = logging.getLogger(__name__)

PROLONGED_OUTAGE_MINUTES = 5


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
