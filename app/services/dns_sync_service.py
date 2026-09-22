"""Panel side of the DNS sync: build the full snapshot and push it to a node."""
import logging
from datetime import datetime

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.dns_node import DNSNode
from app.schemas.dns_node import DNSNodeCommandResult
from app.schemas.sync import (
    DNSSyncPayload, UserSync, OrganizationSync, DomainSync,
    DNSRecordSync, EdgeNodeSync, DNSNodeSync
)

logger = logging.getLogger(__name__)

# Per-node sync timeout. Kept well below the Celery soft time limit (120s) so a
# single unreachable node cannot eat the whole task budget and starve the
# remaining nodes — a stale replica keeps serving dead edge IPs.
SYNC_TIMEOUT_SECONDS = 20.0


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


async def sync_node(node: DNSNode, db_session: AsyncSession) -> DNSNodeCommandResult:
    """Sync domains and records from central DB to node DB via API"""
    try:
        payload = await build_sync_payload(db_session)

        # Need to determine port, assuming 8000 for now
        api_url = f"http://{node.ip_address}:8000/api/v1/sync"
        headers = {}
        if settings.NODE_SYNC_TOKEN:
            headers["X-Node-Token"] = settings.NODE_SYNC_TOKEN

        async with httpx.AsyncClient() as client:
            response = await client.post(
                api_url,
                json=payload.model_dump(mode='json'),
                headers=headers,
                timeout=SYNC_TIMEOUT_SECONDS
            )

            if response.status_code == 200:
                node.last_sync_at = datetime.utcnow()
                await db_session.commit()
                return DNSNodeCommandResult(
                    success=True,
                    stdout=str(response.json()),
                    stderr="",
                    exit_code=0,
                    execution_time=response.elapsed.total_seconds()
                )
            else:
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
