from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, BigInteger, SmallInteger
from sqlalchemy.orm import backref, relationship
from datetime import datetime

from app.core.database import Base

class RequestLog(Base):
    __tablename__ = "request_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    domain_id = Column(Integer, ForeignKey("domains.id", ondelete="CASCADE"), nullable=True, index=True)
    # passive_deletes: логи удаляет каскад в БД, а не ORM построчно.
    domain = relationship("Domain", backref=backref("logs", passive_deletes=True))
    
    edge_node_id = Column(Integer, ForeignKey("edge_nodes.id", ondelete="SET NULL"), nullable=True)
    edge_node = relationship("EdgeNode", backref="logs")

    # Хост запроса как есть (app.example.com): зона живёт в domain_id, а
    # разбивка по поддоменам — здесь.
    host = Column(String(255), nullable=True)
    # Отпечаток строки лога. Нода повторяет партию, если не дождалась ответа,
    # и без уникального отпечатка каждая такая партия ложилась в таблицу ещё
    # раз (21% дублей за 1–3.09.2026). Вставка — ON CONFLICT DO NOTHING.
    fingerprint = Column(BigInteger, nullable=True, unique=True)

    # Request details
    method = Column(String(10))
    path = Column(String(2048))
    query_string = Column(String(2048), nullable=True)
    status_code = Column(Integer)
    bytes_sent = Column(BigInteger)
    
    # Client details
    client_ip = Column(String(45))
    user_agent = Column(String(512), nullable=True)
    referer = Column(String(2048), nullable=True)
    
    # Performance & Security
    request_time = Column(Integer)  # мс: запрос на ноде целиком, вместе с ожиданием origin
    # Время ответа origin (мс, сумма при повторах) и его код: отличить
    # «тормозит сайт» от «тормозит CDN». У ответов из кэша — NULL.
    upstream_time = Column(Integer, nullable=True)
    upstream_status = Column(SmallInteger, nullable=True)
    bytes_received = Column(BigInteger, nullable=True)  # $request_length
    cache_status = Column(String(20)) # HIT, MISS, BYPASS
    waf_status = Column(String(20), nullable=True) # BLOCKED, ALLOWED, CHALLENGED
    waf_rule_id = Column(Integer, nullable=True)
    
    # Geo
    country_code = Column(String(2), nullable=True)

    # Кто прислал запрос (app/services/traffic_class.py): human, vpn, app —
    # люди; search, ai, seo, preview, monitor, archive, bot, tool, scanner,
    # hosted — боты. Сеть клиента — номер AS из GeoLite2-ASN.
    asn = Column(Integer, nullable=True)
    client_class = Column(String(10), nullable=True)

