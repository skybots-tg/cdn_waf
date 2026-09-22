"""DNS node side of the sync: replace the local tables with the panel's snapshot."""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.sync import DNSSyncPayload
from app.services.dns_sync_guard import SnapshotCounts, payload_counts, snapshot_problem

logger = logging.getLogger("dns_server")

# Serialises concurrent syncs. The guard reads the tables before TRUNCATE, so
# two syncs would each hold a share lock the other's TRUNCATE waits for.
SYNC_LOCK_KEY = 0x444E5353594E43  # "DNSSYNC"

USER_DEFAULTS = {
    "totp_enabled": False,
    "totp_secret": None,
}
EDGE_NODE_DEFAULTS = {
    "config_version": 0,
    "last_heartbeat": None,
    "cpu_usage": None,
    "memory_usage": None,
    "disk_usage": None,
    "last_config_update": None,
    "ssh_host": None,
    "ssh_port": None,
    "ssh_user": None,
    "ssh_key": None,
    "ssh_password": None,
}
DNS_NODE_DEFAULTS = {
    "ssh_host": None,
    "ssh_port": None,
    "ssh_user": None,
    "ssh_key": None,
    "ssh_password": None,
}


def existing_sync_tables(db: Session) -> list[str]:
    """Sync tables that exist in the local schema."""
    return db.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
        "AND tablename IN ('dns_records','domains','organizations','users','edge_nodes','dns_nodes')"
    )).scalars().all()


class SnapshotRejected(Exception):
    """The snapshot looks like an outage on the panel; nothing was touched."""

    def __init__(self, reason: str, current: SnapshotCounts, incoming: SnapshotCounts):
        super().__init__(reason)
        self.reason = reason
        self.current = current
        self.incoming = incoming

    def detail(self) -> dict:
        return {
            "error": "snapshot_rejected",
            "reason": self.reason,
            "current": self.current.as_dict(),
            "incoming": self.incoming.as_dict(),
            "hint": "resend with ?force=true to apply it anyway",
        }


def replace_snapshot(db: Session, payload: DNSSyncPayload, force: bool = False) -> None:
    """TRUNCATE the sync tables and insert the payload. The caller commits.

    Unless force is set, raises SnapshotRejected before touching anything when
    the payload would wipe or gut the local zones (see dns_sync_guard).
    """
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SYNC_LOCK_KEY})
    existing = existing_sync_tables(db)
    if not force:
        check_snapshot(db, existing, payload)
    if existing:
        db.execute(text(f"TRUNCATE TABLE {', '.join(existing)} RESTART IDENTITY CASCADE"))

    # Parents before children: FKs are checked on every INSERT.
    if payload.users:
        insert_rows(db, "users", [u.model_dump() for u in payload.users], USER_DEFAULTS)
    if payload.organizations:
        insert_rows(db, "organizations", [o.model_dump() for o in payload.organizations])
    if payload.domains:
        insert_rows(db, "domains", [d.model_dump() for d in payload.domains])
    if payload.records:
        insert_rows(db, "dns_records", [r.model_dump() for r in payload.records])
    if payload.edge_nodes:
        insert_rows(db, "edge_nodes", [n.model_dump() for n in payload.edge_nodes], EDGE_NODE_DEFAULTS)
    if payload.dns_nodes:
        insert_rows(db, "dns_nodes", [n.model_dump() for n in payload.dns_nodes], DNS_NODE_DEFAULTS)


def check_snapshot(db: Session, existing: list[str], payload: DNSSyncPayload) -> None:
    """Raise SnapshotRejected if the payload is far smaller than the local DB."""
    current = local_counts(db, existing)
    incoming = payload_counts(payload)
    problem = snapshot_problem(incoming, current)
    if problem:
        raise SnapshotRejected(problem, current, incoming)


def local_counts(db: Session, existing: list[str]) -> SnapshotCounts:
    def count(table: str) -> int:
        if table not in existing:
            return 0
        return db.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0

    return SnapshotCounts(domains=count("domains"), records=count("dns_records"))


def insert_rows(db: Session, table_name: str, rows: list[dict], defaults: dict | None = None):
    """Insert rows only into existing columns to avoid schema drift issues."""
    if not rows:
        return
    defaults = defaults or {}
    cols_res = db.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = :table_name"
        ),
        {"table_name": table_name},
    )
    table_columns = [r[0] for r in cols_res]
    if not table_columns:
        logger.warning(f"Sync: table {table_name} does not exist, skipping {len(rows)} rows")
        return
    # Use only columns that exist both in DB and in incoming rows
    used_columns = [c for c in table_columns if any(c in row for row in rows) or c in defaults]
    if not used_columns:
        return
    stmt = text(
        f"INSERT INTO {table_name} ({', '.join(used_columns)}) "
        f"VALUES ({', '.join(':'+c for c in used_columns)})"
    )
    filtered_rows = [
        {c: row.get(c, defaults.get(c)) for c in used_columns}
        for row in rows
    ]
    db.execute(stmt, filtered_rows)
