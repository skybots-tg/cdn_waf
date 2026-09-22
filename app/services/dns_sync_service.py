"""Panel side of the DNS sync: build the full snapshot and push it to a node.

Before sending, the snapshot is checked against the last one a node accepted
(kept in Redis), so a broken panel DB never reaches the nodes — even ones still
running code without their own check. The node repeats the check against its
local DB and answers 409. Either refusal is logged, alerted to Telegram and
returned with exit_code SYNC_REFUSED_EXIT_CODE; force=True skips both checks.
"""
import json
import logging
from datetime import datetime
from typing import Optional

import httpx
import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.dns_node import DNSNode
from app.schemas.dns_node import DNSNodeCommandResult
from app.schemas.sync import (
    DNSSyncPayload, UserSync, OrganizationSync, DomainSync,
    DNSRecordSync, EdgeNodeSync, DNSNodeSync
)
from app.services.alert_service import AlertService
from app.services.dns_sync_guard import SnapshotCounts, payload_counts, snapshot_problem

logger = logging.getLogger(__name__)

# Per-node sync timeout. Kept well below the Celery soft time limit (120s) so a
# single unreachable node cannot eat the whole task budget and starve the
# remaining nodes — a stale replica keeps serving dead edge IPs.
SYNC_TIMEOUT_SECONDS = 20.0

SYNC_REFUSED_EXIT_CODE = 409  # the guard (panel or node) refused the snapshot
LAST_ACCEPTED_KEY = "dns:sync:last_accepted"
PANEL_ALERT_KEY = "dns:sync:refused_alert:panel"
GUARD_ALERT_COOLDOWN_SECONDS = 1800  # sync runs every 10 min and after edits
REDIS_TIMEOUT_SECONDS = 3


async def build_sync_payload(db_session: AsyncSession) -> DNSSyncPayload:
    """Read everything a DNS node needs from the central DB."""
    users = (await db_session.execute(text("SELECT * FROM users"))).all()
    organizations = (await db_session.execute(text("SELECT * FROM organizations"))).all()
    domains = (await db_session.execute(text("SELECT * FROM domains"))).all()
    dns_records = (await db_session.execute(text("SELECT * FROM dns_records"))).all()
    edge_nodes = (await db_session.execute(text("SELECT * FROM edge_nodes"))).all()
    dns_nodes = (await db_session.execute(text("SELECT * FROM dns_nodes"))).all()

    def row_to_dict(row):
        return dict(row._mapping)

    def user_row(row):
        # The DNS node never authenticates users — it only serves DNS —
        # so never ship password hashes / TOTP secrets over the wire.
        d = row_to_dict(row)
        d["password_hash"] = ""
        d["totp_secret"] = None
        return d

    return DNSSyncPayload(
        users=[UserSync(**user_row(u)) for u in users],
        organizations=[OrganizationSync(**row_to_dict(o)) for o in organizations],
        domains=[DomainSync(**row_to_dict(d)) for d in domains],
        records=[DNSRecordSync(**row_to_dict(r)) for r in dns_records],
        edge_nodes=[EdgeNodeSync(**row_to_dict(n)) for n in edge_nodes],
        dns_nodes=[DNSNodeSync(**row_to_dict(n)) for n in dns_nodes],
    )


async def sync_node(
    node: DNSNode, db_session: AsyncSession, force: bool = False
) -> DNSNodeCommandResult:
    """Sync domains and records from central DB to node DB via API"""
    try:
        payload = await build_sync_payload(db_session)
        incoming = payload_counts(payload)
        async with GuardState() as state:
            if not force:
                last = await state.last_accepted()
                problem = snapshot_problem(incoming, last) if last else None
                if problem:
                    return await _refused(
                        state, node, "panel", problem, PANEL_ALERT_KEY,
                        "панель, снапшот не отправлен ни на одну DNS-ноду",
                    )

            response = await _post_snapshot(node, payload, force)

            if response.status_code == 200:
                node.last_sync_at = datetime.utcnow()
                await db_session.commit()
                await state.remember_accepted(incoming)
                await state.forget_alerts(_node_alert_key(node), PANEL_ALERT_KEY)
                return DNSNodeCommandResult(
                    success=True,
                    stdout=str(response.json()),
                    stderr="",
                    exit_code=0,
                    execution_time=response.elapsed.total_seconds()
                )
            if response.status_code == 409:
                return await _refused(
                    state, node, "node", _node_refusal_reason(response),
                    _node_alert_key(node), f"DNS-нода {node.name} ({node.ip_address})",
                )
            return DNSNodeCommandResult(
                success=False,
                stdout=response.text,
                stderr=f"API Error: {response.status_code}",
                exit_code=1,
                execution_time=response.elapsed.total_seconds()
            )

    except Exception as e:
        logger.error(f"Sync failed to {node.name}: {e}")
        return DNSNodeCommandResult(
            success=False,
            stdout="",
            stderr=str(e),
            exit_code=1,
            execution_time=0.0
        )


async def _post_snapshot(node: DNSNode, payload: DNSSyncPayload, force: bool) -> httpx.Response:
    # Need to determine port, assuming 8000 for now
    api_url = f"http://{node.ip_address}:8000/api/v1/sync"
    headers = {}
    if settings.NODE_SYNC_TOKEN:
        headers["X-Node-Token"] = settings.NODE_SYNC_TOKEN
    async with _http_client() as client:
        return await client.post(
            api_url,
            json=payload.model_dump(mode='json'),
            params={"force": "true"} if force else None,
            headers=headers,
            timeout=SYNC_TIMEOUT_SECONDS
        )


def _http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient()


async def _refused(
    state: "GuardState", node: DNSNode, side: str, reason: str, alert_key: str, where: str,
) -> DNSNodeCommandResult:
    """Log, alert (once per cooldown) and report a snapshot the guard refused."""
    message = (
        f"Snapshot refused by {side} guard: {reason}. DNS zones on the node are "
        "unchanged; resend with force to apply it anyway."
    )
    logger.error("DNS sync to %s: %s", node.name, message)
    if await state.claim_alert(alert_key):
        await AlertService.dns_sync_refused(where, reason)
    return DNSNodeCommandResult(
        success=False,
        stdout="",
        stderr=message,
        exit_code=SYNC_REFUSED_EXIT_CODE,
        execution_time=0.0,
    )


def _node_refusal_reason(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, dict) and detail.get("reason"):
        return str(detail["reason"])
    return response.text[:300] or f"HTTP {response.status_code}"


def _node_alert_key(node: DNSNode) -> str:
    return f"dns:sync:refused_alert:{node.id}"


def _open_redis():
    return aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
        socket_timeout=REDIS_TIMEOUT_SECONDS,
    )


class GuardState:
    """What the guard remembers between syncs, in Redis.

    Uses its own short-lived connection: sync runs both in cdn_app and in
    Celery tasks, where the shared redis_client may be unconnected or bound to
    a finished event loop. Without Redis nothing is remembered — the panel-side
    check is skipped (the node still checks) and alerts go out uncapped.
    """

    def __init__(self):
        self._redis = None

    async def __aenter__(self) -> "GuardState":
        try:
            self._redis = _open_redis()
        except Exception as e:
            logger.warning("DNS sync guard: Redis unavailable: %s", e)
        return self

    async def __aexit__(self, *_exc) -> None:
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass

    async def _call(self, method: str, *args, **kwargs):
        if self._redis is None:
            raise ConnectionError("no Redis connection")
        return await getattr(self._redis, method)(*args, **kwargs)

    async def last_accepted(self) -> Optional[SnapshotCounts]:
        try:
            raw = await self._call("get", LAST_ACCEPTED_KEY)
            return SnapshotCounts.from_dict(json.loads(raw)) if raw else None
        except Exception as e:
            logger.warning("DNS sync guard: cannot read last accepted snapshot: %s", e)
            return None

    async def remember_accepted(self, counts: SnapshotCounts) -> None:
        try:
            await self._call("set", LAST_ACCEPTED_KEY, json.dumps(counts.as_dict()))
        except Exception as e:
            logger.warning("DNS sync guard: cannot store accepted snapshot: %s", e)

    async def claim_alert(self, key: str) -> bool:
        """True if no alert for key went out within the cooldown (and start one)."""
        try:
            return bool(await self._call(
                "set", key, "1", ex=GUARD_ALERT_COOLDOWN_SECONDS, nx=True,
            ))
        except Exception as e:
            logger.warning("DNS sync guard: alert cooldown unavailable: %s", e)
            return True

    async def forget_alerts(self, *keys: str) -> None:
        try:
            await self._call("delete", *keys)
        except Exception as e:
            logger.warning("DNS sync guard: cannot reset alert cooldown: %s", e)
