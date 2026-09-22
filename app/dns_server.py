import asyncio
import logging
import os
import signal
import sys
import threading
from datetime import datetime
from typing import List, Optional

from dnslib import (
    DNSRecord, DNSHeader, RR, QTYPE, A, AAAA, CNAME, MX, NS, SOA, TXT,
    RCODE, CLASS, DNSLabel
)
from dnslib.server import DNSServer, BaseResolver
from sqlalchemy import create_engine, select, and_, or_
from sqlalchemy.orm import sessionmaker, Session
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Header
import uvicorn

from app.core.config import settings
from app.models.domain import Domain, DomainStatus
from app.models.dns import DNSRecord as DNSModel
from app.models.edge_node import EdgeNode
from app.models.dns_node import DNSNode
from app.models.user import User
from app.models.organization import Organization
from app.schemas.sync import DNSSyncPayload
from app.dns_node_sync import SnapshotRejected, replace_snapshot

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("dns_server")

# Sync Database Connection
# We need to replace 'postgresql+asyncpg' with 'postgresql' for sync driver
SYNC_DATABASE_URL = str(settings.DATABASE_URL).replace("postgresql+asyncpg", "postgresql")

# Fix for localhost connection issues in some environments (like Docker vs Host)
if "@db:" not in SYNC_DATABASE_URL and ("@localhost" in SYNC_DATABASE_URL or "@127.0.0.1" in SYNC_DATABASE_URL):
    # Try to use 127.0.0.1 explicitly instead of localhost to avoid IPv6 issues if PG is only IPv4
    SYNC_DATABASE_URL = SYNC_DATABASE_URL.replace("@localhost", "@127.0.0.1")

engine = create_engine(SYNC_DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class DBResolver(BaseResolver):
    """
    DNS Resolver backed by PostgreSQL database
    """
    
    def __init__(self):
        from app.core.config import settings
        ns_list = [ns.strip() for ns in settings.EXPECTED_NS.split(",")]
        self.ns1 = ns_list[0] if len(ns_list) > 0 else "ns1.flarecloud.ru"
        self.ns2 = ns_list[1] if len(ns_list) > 1 else "ns2.flarecloud.ru"
        acme_email = settings.ACME_EMAIL.replace("@", ".")
        self.admin_email = acme_email
        self.ttl = 300
        
    def get_nameservers(self, db: Session) -> List[str]:
        """Get hostnames of active DNS nodes"""
        try:
            nodes = db.execute(
                select(DNSNode).where(DNSNode.enabled == True)
            ).scalars().all()
            if nodes:
                return [node.hostname for node in nodes]
        except Exception as e:
            logger.warning(f"get_nameservers failed (using defaults): {e}")
            db.rollback()
        return [self.ns1, self.ns2]

    def get_edge_nodes_ips(self, db: Session) -> List[str]:
        """Get IPs of active edge nodes"""
        try:
            nodes = db.execute(
                select(EdgeNode).where(
                    and_(EdgeNode.status == "online", EdgeNode.enabled == True)
                )
            ).scalars().all()
            return [node.ip_address for node in nodes]
        except Exception as e:
            logger.warning(f"get_edge_nodes_ips failed: {e}")
            db.rollback()
            return []

    def _make_soa(self, zone_qname, ns_list):
        """Build SOA RR for authority section / SOA queries."""
        primary_ns = ns_list[0] if ns_list else self.ns1
        return RR(
            zone_qname,
            QTYPE.SOA,
            ttl=self.ttl,
            rdata=SOA(
                mname=primary_ns,
                rname=self.admin_email,
                times=(
                    int(datetime.utcnow().strftime("%Y%m%d%H")),
                    3600, 600, 86400, self.ttl,
                )
            )
        )

    def _add_authority(self, reply, zone_qname, ns_list):
        """Add NS records to the AUTHORITY section (RFC 1035 s4.3.1)."""
        for ns in ns_list:
            reply.add_auth(RR(zone_qname, QTYPE.NS, ttl=self.ttl, rdata=NS(ns)))

    @staticmethod
    def _make_txt_rdata(content: str) -> TXT:
        """Create TXT RDATA, splitting content > 255 bytes into chunks."""
        raw = content.encode("utf-8")
        if len(raw) <= 255:
            return TXT(raw)
        chunks = [raw[i:i+255] for i in range(0, len(raw), 255)]
        return TXT(chunks)

    def resolve(self, request: DNSRecord, handler) -> DNSRecord:
        reply = request.reply()
        qname = request.q.qname
        qtype_num = request.q.qtype
        qtype_name = QTYPE[qtype_num]
        
        domain_name = str(qname).rstrip('.').lower()
        
        logger.info(f"DNS query: {domain_name} {qtype_name}")
        
        try:
            return self._do_resolve(reply, qname, qtype_name, domain_name)
        except Exception:
            logger.exception(f"Error resolving {domain_name} {qtype_name}")
            reply.header.rcode = RCODE.SERVFAIL
            return reply

    def _do_resolve(self, reply, qname, qtype_name, domain_name) -> DNSRecord:
        with SessionLocal() as db:
            parts = domain_name.split('.')
            zone = None
            zone_domain = None
            
            for i in range(len(parts)):
                candidate = ".".join(parts[i:])
                domain = db.execute(
                    select(Domain).where(Domain.name == candidate)
                ).scalar_one_or_none()
                
                if domain:
                    zone = domain
                    zone_domain = candidate
                    break
            
            if not zone:
                logger.info(f"  -> REFUSED (no zone for {domain_name})")
                reply.header.rcode = RCODE.REFUSED
                return reply

            if zone.status not in [DomainStatus.ACTIVE, DomainStatus.PENDING]:
                logger.info(f"  -> REFUSED (zone {zone_domain} status={zone.status})")
                reply.header.rcode = RCODE.REFUSED
                return reply

            if domain_name == zone_domain:
                record_name = "@"
            else:
                record_name = domain_name[:-len(zone_domain)-1]
            
            logger.info(f"  zone={zone_domain} (id={zone.id}), record_name={record_name!r}")

            ns_list = self.get_nameservers(db)
            zone_qname = DNSLabel(zone_domain + ".")

            if qtype_name == "SOA":
                reply.add_answer(self._make_soa(zone_qname, ns_list))
                self._add_authority(reply, zone_qname, ns_list)
                return reply

            if qtype_name == "NS" and record_name == "@":
                for ns in ns_list:
                    reply.add_answer(RR(qname, QTYPE.NS, ttl=self.ttl, rdata=NS(ns)))
                return reply

            records = db.execute(
                select(DNSModel).where(
                    and_(
                        DNSModel.domain_id == zone.id,
                        or_(
                            DNSModel.name == record_name,
                            DNSModel.name == domain_name
                        )
                    )
                )
            ).scalars().all()
            
            logger.info(
                f"  DB returned {len(records)} records "
                f"(names: {[r.name for r in records]}, types: {[r.type for r in records]})"
            )

            matching_records = [r for r in records if r.type == qtype_name]
            cname_records = [r for r in records if r.type == 'CNAME']

            target_record = next((r for r in matching_records), None)
            
            is_proxied = False
            
            if target_record and target_record.proxied and qtype_name in ['A', 'AAAA']:
                is_proxied = True
            elif cname_records and cname_records[0].proxied and qtype_name in ['A', 'AAAA', 'CNAME']:
                is_proxied = True
            
            if is_proxied and qtype_name in ['A', 'AAAA']:
                edge_ips = self.get_edge_nodes_ips(db)
                if not edge_ips:
                    logger.warning("No active edge nodes found! Returning origin records.")
                    is_proxied = False
                else:
                    for ip in edge_ips:
                        if '.' in ip and qtype_name == 'A':
                            reply.add_answer(RR(qname, QTYPE.A, ttl=60, rdata=A(ip)))
                        elif ':' in ip and qtype_name == 'AAAA':
                            reply.add_answer(RR(qname, QTYPE.AAAA, ttl=60, rdata=AAAA(ip)))
                    self._add_authority(reply, zone_qname, ns_list)
                    return reply

            if matching_records:
                for r in matching_records:
                    if r.type == 'A':
                        reply.add_answer(RR(qname, QTYPE.A, ttl=r.ttl, rdata=A(r.content)))
                    elif r.type == 'AAAA':
                        reply.add_answer(RR(qname, QTYPE.AAAA, ttl=r.ttl, rdata=AAAA(r.content)))
                    elif r.type == 'CNAME':
                        reply.add_answer(RR(qname, QTYPE.CNAME, ttl=r.ttl, rdata=CNAME(r.content)))
                    elif r.type == 'MX':
                        reply.add_answer(RR(qname, QTYPE.MX, ttl=r.ttl, rdata=MX(r.content, r.priority or 10)))
                    elif r.type == 'TXT':
                        reply.add_answer(RR(qname, QTYPE.TXT, ttl=r.ttl, rdata=self._make_txt_rdata(r.content)))
                    elif r.type == 'NS':
                        reply.add_answer(RR(qname, QTYPE.NS, ttl=r.ttl, rdata=NS(r.content)))
            
            elif cname_records:
                 for r in cname_records:
                     reply.add_answer(RR(qname, QTYPE.CNAME, ttl=r.ttl, rdata=CNAME(r.content)))

            if reply.rr:
                logger.info(f"  -> NOERROR, {len(reply.rr)} answer(s)")
                self._add_authority(reply, zone_qname, ns_list)
            else:
                if records:
                    reply.header.rcode = RCODE.NOERROR
                    logger.info(f"  -> NODATA (records exist but not type {qtype_name})")
                else:
                    reply.header.rcode = RCODE.NXDOMAIN
                    logger.info(f"  -> NXDOMAIN (no records for {record_name!r} in zone {zone_domain})")
                reply.add_auth(self._make_soa(zone_qname, ns_list))

        return reply

# FastAPI App for management
app = FastAPI(title="DNS Node API")


def require_node_token(x_node_token: Optional[str] = Header(default=None)):
    """Authenticate control-plane -> node requests with a shared token.

    Soft during rollout: if NODE_SYNC_TOKEN is not set in this node's env, we log
    a warning and allow the request, so sync keeps working until the token is
    distributed to every node. Once the token is set, a missing/wrong token is
    rejected with 401. Combined with the firewall that limits :8000 to the
    control-plane IP, this closes the unauthenticated sync/debug endpoints.
    """
    expected = getattr(settings, "NODE_SYNC_TOKEN", None)
    if not expected:
        logger.warning(
            "NODE_SYNC_TOKEN not configured on this node — accepting request without token auth"
        )
        return
    if x_node_token != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing node token")


@app.get("/api/v1/debug/lookup")
def debug_lookup(name: str, type: str = "TXT", _auth: None = Depends(require_node_token)):
    """Diagnostic endpoint: show exactly what the DB contains for a given query."""
    name = name.rstrip('.').lower()
    qtype = type.upper()

    with SessionLocal() as db:
        parts = name.split('.')
        zone = None
        zone_domain = None

        for i in range(len(parts)):
            candidate = ".".join(parts[i:])
            domain = db.execute(
                select(Domain).where(Domain.name == candidate)
            ).scalar_one_or_none()
            if domain:
                zone = domain
                zone_domain = candidate
                break

        if not zone:
            return {"error": "no_zone", "detail": f"No zone found for {name}"}

        if name == zone_domain:
            record_name = "@"
        else:
            record_name = name[:-len(zone_domain) - 1]

        records = db.execute(
            select(DNSModel).where(DNSModel.domain_id == zone.id)
        ).scalars().all()

        all_records = [
            {"id": r.id, "name": r.name, "type": r.type, "content": r.content[:80], "ttl": r.ttl}
            for r in records
        ]

        matched = [
            r for r in records
            if r.name in (record_name, name) and r.type == qtype
        ]

        return {
            "query_name": name,
            "query_type": qtype,
            "zone": zone_domain,
            "zone_id": zone.id,
            "zone_status": str(zone.status),
            "record_name_computed": record_name,
            "total_records_in_zone": len(records),
            "all_record_names": sorted(set(r.name for r in records)),
            "matched_records": [
                {"id": r.id, "name": r.name, "type": r.type, "content": r.content, "ttl": r.ttl}
                for r in matched
            ],
            "all_records": all_records,
        }


@app.post("/api/v1/sync")
async def sync_data(
    payload: DNSSyncPayload,
    force: bool = False,
    _auth: None = Depends(require_node_token),
):
    """Sync data from central server.

    A snapshot that would wipe or gut the local zones is refused with 409 and
    nothing is touched, unless the panel resends it with ?force=true.
    """
    logger.info("Received sync request%s", " (force)" if force else "")
    try:
        with SessionLocal() as db:
            replace_snapshot(db, payload, force=force)
            db.commit()
            logger.info("Sync completed successfully")
            return {"status": "success", "count": {
                "users": len(payload.users),
                "domains": len(payload.domains),
                "records": len(payload.records),
                "edge_nodes": len(payload.edge_nodes)
            }}
            
    except SnapshotRejected as e:
        logger.error(
            "Sync refused, local zones kept: %s (local=%s, incoming=%s)",
            e.reason, e.current.as_dict(), e.incoming.as_dict(),
        )
        raise HTTPException(status_code=409, detail=e.detail())
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def start_dns_server():
    resolver = DBResolver()
    
    # Create UDP Server
    udp_server = DNSServer(resolver, port=53, address="0.0.0.0", tcp=False)
    # Create TCP Server
    tcp_server = DNSServer(resolver, port=53, address="0.0.0.0", tcp=True)

    logger.info("Starting DNS Server on port 53...")
    
    udp_server.start_thread()
    tcp_server.start_thread()
    
    return udp_server, tcp_server

@app.on_event("startup")
def startup_event():
    # Start DNS server in background
    start_dns_server()

if __name__ == "__main__":
    # Run API server
    # This entry point is used when running python -m app.dns_server
    uvicorn.run(app, host="0.0.0.0", port=8000)
