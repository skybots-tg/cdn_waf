"""DNS node side of the sync: replace the local tables with the panel's snapshot."""
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.sync import DNSSyncPayload

logger = logging.getLogger("dns_server")

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


def replace_snapshot(db: Session, payload: DNSSyncPayload) -> None:
    """TRUNCATE the sync tables and insert the payload. The caller commits."""
    existing = existing_sync_tables(db)
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
