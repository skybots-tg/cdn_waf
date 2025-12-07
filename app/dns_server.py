import asyncio
import logging
import os
import signal
import sys
from datetime import datetime
from typing import List, Optional

from dnslib import (
    DNSRecord, DNSHeader, RR, QTYPE, A, AAAA, CNAME, MX, NS, SOA, TXT,
    RCODE, CLASS, DNSLabel
)
from dnslib.server import DNSServer, BaseResolver
from sqlalchemy import create_engine, select, and_
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings
from app.models.domain import Domain, DomainStatus
from app.models.dns import DNSRecord as DNSModel
from app.models.edge_node import EdgeNode

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("dns_server")

# Sync Database Connection
# We need to replace 'postgresql+asyncpg' with 'postgresql' for sync driver
SYNC_DATABASE_URL = str(settings.DATABASE_URL).replace("postgresql+asyncpg", "postgresql")
engine = create_engine(SYNC_DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class DBResolver(BaseResolver):
    """
    DNS Resolver backed by PostgreSQL database
    """
    
    def __init__(self):
        self.ns1 = "ns1.yourcdn.ru"
        self.ns2 = "ns2.yourcdn.ru"
        self.admin_email = "admin.yourcdn.ru"
        self.ttl = 300
        
    def get_edge_nodes_ips(self, db: Session) -> List[str]:
        """Get IPs of active edge nodes"""
        nodes = db.execute(
            select(EdgeNode).where(
                and_(EdgeNode.status == "online", EdgeNode.enabled == True)
            )
        ).scalars().all()
        return [node.ip_address for node in nodes]

    def resolve(self, request: DNSRecord, handler) -> DNSRecord:
        reply = request.reply()
        qname = request.q.qname
        qtype_num = request.q.qtype
        qtype_name = QTYPE[qtype_num]
        
        domain_name = str(qname).rstrip('.')
        
        logger.info(f"Query: {qname} ({qtype_name})")
        
        with SessionLocal() as db:
            # 1. Find the domain (zone)
            # We need to find the longest matching domain in our DB
            # e.g. for "sub.example.com", we might host "example.com"
            
            parts = domain_name.split('.')
            zone = None
            zone_domain = None
            
            # Try to match domain from specific to general
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
                logger.debug(f"Domain not found: {domain_name}")
                reply.header.rcode = RCODE.REFUSED # We are not authoritative
                return reply
                
            if zone.status != DomainStatus.ACTIVE:
                logger.debug(f"Domain inactive: {zone.name}")
                reply.header.rcode = RCODE.REFUSED
                return reply

            # Calculate relative name for DB lookup
            # if query is "www.example.com" and zone is "example.com", name is "www"
            # if query is "example.com", name is "@"
            
            if domain_name == zone_domain:
                record_name = "@"
            else:
                # remove zone suffix
                record_name = domain_name[:-len(zone_domain)-1]
            
            # Handle SOA
            if qtype_name == "SOA":
                reply.add_answer(RR(
                    qname,
                    QTYPE.SOA,
                    ttl=self.ttl,
                    rdata=SOA(
                        mname=self.ns1,
                        rname=self.admin_email,
                        serial=int(datetime.utcnow().strftime("%Y%m%d%H")),
                        refresh=3600,
                        retry=600,
                        expire=86400,
                        minttl=self.ttl
                    )
                ))
                return reply

            # Handle NS for apex
            if qtype_name == "NS" and record_name == "@":
                reply.add_answer(RR(qname, QTYPE.NS, ttl=self.ttl, rdata=NS(self.ns1)))
                reply.add_answer(RR(qname, QTYPE.NS, ttl=self.ttl, rdata=NS(self.ns2)))
                return reply

            # Look for records
            records = db.execute(
                select(DNSModel).where(
                    and_(DNSModel.domain_id == zone.id, DNSModel.name == record_name)
                    # We might want to filter by type, but CNAME handling is special
                )
            ).scalars().all()
            
            # Filter for specific type or CNAME
            matching_records = [r for r in records if r.type == qtype_name]
            cname_records = [r for r in records if r.type == 'CNAME']
            
            # If we found CNAME but query was not for CNAME, we should follow it (or just return it?)
            # Standard behavior: return CNAME. Recursive resolver will follow.
            # BUT if it's proxied, we return A records of edge nodes!
            
            final_records = []
            
            # Logic for Proxied records (A, AAAA, CNAME)
            # If any record for this name is proxied, we return Edge Node IPs
            is_proxied = any(r.proxied for r in records if r.type in ['A', 'AAAA', 'CNAME'])
            
            if is_proxied and qtype_name in ['A', 'AAAA']:
                # Return Edge Node IPs
                edge_ips = self.get_edge_nodes_ips(db)
                if not edge_ips:
                    # Fallback to origin if no edge nodes? Or fail?
                    # Let's fallback to configured records if no edge nodes available (safe mode)
                    logger.warning("No active edge nodes found! Returning origin records.")
                    is_proxied = False
                else:
                    for ip in edge_ips:
                        # Simple check for IPv4 vs IPv6 (TODO: better check)
                        if '.' in ip and qtype_name == 'A':
                            reply.add_answer(RR(qname, QTYPE.A, ttl=60, rdata=A(ip)))
                        elif ':' in ip and qtype_name == 'AAAA':
                            reply.add_answer(RR(qname, QTYPE.AAAA, ttl=60, rdata=AAAA(ip)))
                    return reply

            # If not proxied or not A/AAAA query on proxied record
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
                        reply.add_answer(RR(qname, QTYPE.TXT, ttl=r.ttl, rdata=TXT(r.content)))
                    elif r.type == 'NS':
                        reply.add_answer(RR(qname, QTYPE.NS, ttl=r.ttl, rdata=NS(r.content)))
            
            elif cname_records:
                 # If we have a CNAME but asked for A/AAAA, return the CNAME
                 for r in cname_records:
                     reply.add_answer(RR(qname, QTYPE.CNAME, ttl=r.ttl, rdata=CNAME(r.content)))

            # If no answers, it might be NXDOMAIN or just empty (NODATA)
            if not reply.rr:
                # If we have records for this name but not this type, it's NOERROR (NODATA)
                # If we have no records for this name, it's NXDOMAIN
                if records:
                     reply.header.rcode = RCODE.NOERROR
                else:
                     reply.header.rcode = RCODE.NXDOMAIN

        return reply

def main():
    resolver = DBResolver()
    
    # Create UDP Server
    udp_server = DNSServer(resolver, port=53, address="0.0.0.0", tcp=False)
    # Create TCP Server
    tcp_server = DNSServer(resolver, port=53, address="0.0.0.0", tcp=True)

    logger.info("Starting DNS Server on port 53...")
    
    udp_server.start_thread()
    tcp_server.start_thread()

    try:
        while udp_server.is_alive():
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        udp_server.stop()
        tcp_server.stop()

if __name__ == "__main__":
    main()
