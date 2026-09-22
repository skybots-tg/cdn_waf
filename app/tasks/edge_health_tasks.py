"""Edge node health check: probes, auto-disable and auto-recovery"""
import asyncio
import logging
from datetime import datetime

import httpx
from sqlalchemy import select

from app.tasks import celery_app
from app.tasks.edge_health_guard import (
    EDGE_MIN_ENABLED_NODES,
    can_auto_disable,
    checker_is_online,
    is_mass_failure,
)
from app.tasks.utils import create_task_db_session

logger = logging.getLogger(__name__)

EDGE_HTTP_TIMEOUT = 5
EDGE_STALE_HEARTBEAT_MINUTES = 8
EDGE_FAILURE_THRESHOLD = 3
EDGE_TLS_TIMEOUT = 6
EDGE_TLS_SAMPLE_SIZE = 3  # proxied hostnames probed per health check
EDGE_ALERT_COOLDOWN_SECONDS = 1800  # 30 min between repeated WARNING alerts
EDGE_MASS_ALERT_KEY = "edge:mass_failure_alert"


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

            # Сначала опрашиваем все ноды разом и только потом решаем: иначе
            # не отличить упавшую ноду от упавшей проверки, а последовательные
            # таймауты при пропавшей сети упираются в soft_time_limit.
            tls_hostnames = await _edge_tls_sample(db)
            probes = await asyncio.gather(
                *(_probe_edge_node(node, tls_hostnames) for node in nodes)
            )
            failing = []
            for node, probe in zip(nodes, probes):
                if _probe_is_healthy(probe):
                    await _mark_edge_healthy(db, redis_client, AlertService, node)
                else:
                    failing.append((node, probe))

            mass_failure = is_mass_failure(len(failing), len(nodes))
            disabled_any = False
            if mass_failure:
                # Раунду не верим: счётчики не трогаем, никого не выключаем.
                await _report_mass_failure(redis_client, AlertService, failing, len(nodes))
            else:
                disabled_any = await _handle_failing_edges(
                    db, redis_client, AlertService, failing, len(nodes),
                )

            if disabled_any:
                sync_dns_nodes.delay()
                logger.info("Triggered DNS sync after edge node auto-disable")

            await _check_auto_disabled_recovery(db, redis_client, AlertService)

            return {
                "status": "ok", "checked": len(nodes),
                "disabled_any": disabled_any, "mass_failure": mass_failure,
            }
    finally:
        await engine.dispose()
        await redis_client.disconnect()


def _probe_is_healthy(probe) -> bool:
    http_ok, stale, _age, tls_ok, _tls_detail = probe
    return http_ok and not stale and tls_ok


async def _mark_edge_healthy(db, redis_client, alert_svc, node):
    """Сбросить счётчик сбоев и вернуть статус online, если нода была offline."""
    redis_key = f"edge:failures:{node.id}"
    if int(await redis_client.get(redis_key) or 0) > 0:
        await redis_client.delete(redis_key)
    await redis_client.delete(f"edge:alert_sent:{node.id}")
    await redis_client.delete(f"edge:alert_kept:{node.id}")
    if node.status == "offline":
        node.status = "online"
        await db.commit()
        logger.info("Edge node %s (%s) recovered", node.name, node.ip_address)
        await alert_svc.edge_node_recovered(node.name, node.ip_address)


async def _report_mass_failure(redis_client, alert_svc, failing, total: int):
    """Лог каждого такого раунда и один CRITICAL-алерт на EDGE_ALERT_COOLDOWN_SECONDS."""
    names = ", ".join(f"{node.name} ({node.ip_address})" for node, _ in failing)
    if await checker_is_online():
        cause = (
            "у панели есть интернет — проверьте cdn_app (heartbeat), маршрут "
            "до хостеров и сертификаты доменов из TLS-выборки"
        )
    else:
        cause = "у самой панели нет выхода в интернет"
    logger.error(
        "Edge health: %d of %d nodes failing at once (%s) — auto-disable "
        "suspended this round: %s", len(failing), total, cause, names,
    )
    if await redis_client.get(EDGE_MASS_ALERT_KEY):
        return
    await redis_client.set(EDGE_MASS_ALERT_KEY, "1", expire=EDGE_ALERT_COOLDOWN_SECONDS)
    await alert_svc.edge_mass_failure(len(failing), total, names, cause)


async def _handle_failing_edges(db, redis_client, alert_svc, failing, enabled_count: int) -> bool:
    """Посчитать сбои и выключить дошедшие до порога ноды, не опускаясь ниже минимума."""
    disabled_any = False
    for node, probe in failing:
        http_ok, stale, age, _tls_ok, tls_detail = probe
        reason = _edge_failure_reason(http_ok, stale, age, tls_detail)
        failures = await _count_edge_failure(redis_client, node, reason)

        if failures < EDGE_FAILURE_THRESHOLD:
            # Устаревший heartbeat или TLS при живом HTTP не спамим —
            # ждём либо восстановления, либо порога автоотключения.
            if not http_ok:
                await _alert_edge_down(redis_client, alert_svc, node, reason)
        elif not can_auto_disable(enabled_count):
            # Отключив ноду, мы увели бы трафик проксируемых доменов
            # на origin в обход CDN/WAF (см. fallback в dns_server).
            logger.warning(
                "Edge node %s (%s) would be auto-disabled but only %d enabled "
                "(min %d) — keeping in rotation: %s",
                node.name, node.ip_address, enabled_count,
                EDGE_MIN_ENABLED_NODES, reason,
            )
            await _alert_edge_down(
                redis_client, alert_svc, node,
                f"{reason} — нода оставлена в ротации, так как включено "
                f"{enabled_count} (минимум {EDGE_MIN_ENABLED_NODES})",
                kind="alert_kept",
            )
        else:
            await _auto_disable_edge(db, redis_client, alert_svc, node, failures, reason)
            enabled_count -= 1
            disabled_any = True
    return disabled_any


async def _count_edge_failure(redis_client, node, reason: str) -> int:
    redis_key = f"edge:failures:{node.id}"
    failures = int(await redis_client.get(redis_key) or 0) + 1
    await redis_client.set(redis_key, str(failures), expire=3600)
    logger.warning(
        "Edge node %s (%s) failing (%d/%d): %s",
        node.name, node.ip_address, failures, EDGE_FAILURE_THRESHOLD, reason,
    )
    return failures


async def _alert_edge_down(redis_client, alert_svc, node, reason: str, kind: str = "alert_sent"):
    """WARNING по ноде не чаще раза в EDGE_ALERT_COOLDOWN_SECONDS на каждый kind."""
    alert_key = f"edge:{kind}:{node.id}"
    if await redis_client.get(alert_key):
        return
    await redis_client.set(alert_key, "1", expire=EDGE_ALERT_COOLDOWN_SECONDS)
    await alert_svc.edge_node_down(node.name, node.ip_address, reason)


async def _auto_disable_edge(db, redis_client, alert_svc, node, failures: int, reason: str):
    node.enabled = False
    node.status = "offline"
    await db.commit()
    await redis_client.delete(f"edge:failures:{node.id}")
    await redis_client.delete(f"edge:alert_sent:{node.id}")
    await redis_client.delete(f"edge:alert_kept:{node.id}")
    await redis_client.set(f"edge:auto_disabled:{node.id}", "1", expire=86400)
    logger.critical(
        "Edge node %s (%s) auto-disabled after %d failures",
        node.name, node.ip_address, failures,
    )
    await alert_svc.edge_node_disabled(
        node.name, node.ip_address,
        f"{failures} неудачных проверок подряд ({reason})",
    )


async def _edge_tls_sample(db) -> list[str]:
    """A few currently-proxied hostnames, used to probe what an edge must serve."""
    from app.models.dns import DNSRecord
    from app.models.domain import Domain

    rows = (await db.execute(
        select(DNSRecord.name, Domain.name)
        .join(Domain, Domain.id == DNSRecord.domain_id)
        .where(DNSRecord.proxied == True, DNSRecord.type == "A")
        .order_by(DNSRecord.id)
    )).all()

    names = []
    for sub, zone in rows:
        fqdn = zone if sub in ("@", "", None) else f"{sub}.{zone}"
        if fqdn not in names:
            names.append(fqdn)
        if len(names) >= EDGE_TLS_SAMPLE_SIZE:
            break
    return names


async def _probe_edge_tls(ip: str, hostnames: list[str]) -> tuple[bool, str]:
    """Verify the node can serve a currently-valid certificate for each hostname.

    A CDN must never route traffic to an edge that cannot terminate TLS, so an
    expired or missing certificate is a health failure, not a cosmetic issue.
    The certificate chain itself is not verified against a trust store — we only
    need the leaf's validity window, and the node answers for names that do not
    match its own address.
    """
    import ssl

    from cryptography import x509
    from cryptography.hazmat.backends import default_backend

    if not hostnames:
        return True, ""

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    now = datetime.utcnow()
    for host in hostnames:
        writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, 443, ssl=ctx, server_hostname=host),
                timeout=EDGE_TLS_TIMEOUT,
            )
            der = writer.get_extra_info("ssl_object").getpeercert(binary_form=True)
            if not der:
                return False, f"нет сертификата для {host}"
            leaf = x509.load_der_x509_certificate(der, default_backend())
            not_after = getattr(leaf, "not_valid_after_utc", None)
            not_after = not_after.replace(tzinfo=None) if not_after else leaf.not_valid_after
            if not_after <= now:
                return False, f"сертификат {host} истёк {not_after:%Y-%m-%d}"
        except Exception as e:
            return False, f"TLS до {host} не установлен ({type(e).__name__})"
        finally:
            if writer is not None:
                writer.close()

    return True, ""


async def _probe_edge_node(
    node, tls_hostnames: list[str] | None = None
) -> tuple[bool, bool, int | None, bool, str]:
    """HTTP probe on port 80 + stale heartbeat + TLS certificate validity.

    Returns (http_ok, stale, heartbeat_age_seconds, tls_ok, tls_detail).
    """
    now = datetime.utcnow()

    age: int | None = None
    if node.last_heartbeat:
        age = int((now - node.last_heartbeat).total_seconds())
        stale = age > EDGE_STALE_HEARTBEAT_MINUTES * 60
    else:
        stale = True

    http_ok = False
    try:
        async with httpx.AsyncClient(timeout=EDGE_HTTP_TIMEOUT) as client:
            resp = await client.get(f"http://{node.ip_address}", follow_redirects=False)
            http_ok = resp.status_code < 600
    except Exception:
        http_ok = False

    tls_ok, tls_detail = await _probe_edge_tls(node.ip_address, tls_hostnames or [])

    return http_ok, stale, age, tls_ok, tls_detail


def _edge_failure_reason(
    http_ok: bool, stale: bool, age: int | None, tls_detail: str = ""
) -> str:
    """Build a truthful reason string based on the actual probe result.

    Avoids the previous behaviour of always appending 'HTTP check failed',
    which produced misleading alerts when the node was actually reachable
    but its heartbeat had merely been delayed.
    """
    parts: list[str] = []
    if stale:
        if age is None:
            parts.append("heartbeat отсутствует")
        else:
            parts.append(f"heartbeat устарел ({age}s)")
    if not http_ok:
        parts.append("HTTP check failed")
    if tls_detail:
        parts.append(tls_detail)
    if not parts:
        parts.append("неизвестная причина")
    return "; ".join(parts)


def _heartbeat_is_fresh(node, max_age_seconds: int = 300) -> bool:
    """Отчитывалась ли нода в последние минуты.

    Признак того, что нода жива и выключена автоматикой, а не человеком:
    выключенная руками нода обычно погашена целиком и heartbeat не шлёт.
    """
    last = getattr(node, "last_heartbeat", None)
    if last is None:
        return False
    from datetime import datetime, timezone

    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - last).total_seconds()
    return 0 <= age <= max_age_seconds


async def _check_auto_disabled_recovery(db, redis_client, alert_svc):
    """Re-enable nodes that were auto-disabled and are now responding.

    Возврат срабатывает по метке `edge:auto_disabled:{id}` в Redis, а если она
    истекла — по свежему heartbeat: нода, которая продолжает отчитываться,
    очевидно жива и выключена не руками. Без этого запаса три ноды провисели
    выключенными и не вернулись: метка живёт сутки, а сбой был раньше.

    Выборка идёт по всем выключенным нодам, без условия на статус. Обработчик
    heartbeat переводит статус в "online", поэтому ожившая нода почти сразу
    переставала подходить под старое условие `status == "offline"` и выпадала
    из проверки навсегда.
    """
    from app.models.edge_node import EdgeNode
    from app.tasks.dns_tasks import sync_dns_nodes

    result = await db.execute(
        select(EdgeNode).where(EdgeNode.enabled == False)
    )
    disabled_nodes = list(result.scalars().all())
    re_enabled_any = False
    tls_hostnames = await _edge_tls_sample(db) if disabled_nodes else []

    for node in disabled_nodes:
        marker = await redis_client.get(f"edge:auto_disabled:{node.id}")
        if not marker and not _heartbeat_is_fresh(node):
            # Ни метки автовыключения, ни признаков жизни — значит ноду
            # выключили руками, и трогать её мы не вправе.
            continue

        try:
            http_ok, stale, age, tls_ok, tls_detail = await _probe_edge_node(
                node, tls_hostnames
            )
            if not tls_ok:
                logger.info(
                    "Auto-disabled edge node %s (%s) still not serving TLS: %s — kept disabled",
                    node.name, node.ip_address, tls_detail,
                )
                continue
            if http_ok and not stale:
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
