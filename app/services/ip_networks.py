"""Сеть клиента по IP: номер AS, её владелец и хостинг ли это.

База — GeoLite2-ASN от MaxMind (те же MAXMIND_ACCOUNT_ID/LICENSE_KEY, что у
GeoIP нод), лежит в ``data/GeoLite2-ASN.mmdb``. Её обновляет задача
``app.tasks.analytics.update_asn_database`` два раза в неделю, а читатель
сам подхватывает новый файл. Без базы всё работает, просто ASN пустой и
браузеры из дата-центров считаются людьми, как было до 24.09.2026.
"""
from __future__ import annotations

import io
import logging
import os
import re
import tarfile
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

DB_PATH = Path(
    os.environ.get("ASN_DB_PATH")
    or Path(__file__).resolve().parents[2] / "data" / "GeoLite2-ASN.mmdb"
)
DOWNLOAD_URL = "https://download.maxmind.com/geoip/databases/GeoLite2-ASN/download?suffix=tar.gz"

# Крупные облака и хостинги по номеру: в названии AS у них не всегда есть
# «hosting» или «cloud» (AMAZON-02, GOOGLE, OVH SAS, YANDEX LLC).
HOSTING_ASNS = frozenset({
    16509, 14618, 8987,            # Amazon
    15169, 396982, 19527, 36040,   # Google, Google Cloud
    8075, 8068, 8069, 12076,       # Microsoft, Azure
    16276, 35540,                  # OVH
    24940, 213230,                 # Hetzner
    14061, 20473, 63949, 12876,    # DigitalOcean, Vultr, Linode, Scaleway
    31898, 45102, 132203, 51167,   # Oracle, Alibaba, Tencent, Contabo
    60781, 28753, 9009, 212238,    # Leaseweb, M247, Datacamp
    30058, 8100, 40676, 21859,     # FDCservers, QuadraNet, Psychz, Zenlayer
    199524, 202422, 49505, 50340,  # G-Core, Selectel
    9123, 197695, 210644, 216246,  # Timeweb, Reg.ru, Aeza
    44477, 62240, 214996, 197540,  # Stark Industries, Clouvider, netcup
    13238, 200350, 47764,          # Yandex, Yandex Cloud, VK
    399629, 11878, 18779, 36352,   # BL Networks, tzulo, EGIHosting, ColoCrossing
    53667, 46562, 29802, 62904,    # FranTech, Performive, HiVelocity, Eonix
    218785, 218751, 207990, 203020,  # TC Datacenter, Fontaine, HostRoyale
    42708, 51747, 201814, 42473,   # Glesys, Internet Vikings, Mevspace, Anexia
    213412, 62874, 47007, 26832,   # ONYPHE, Web2Objects, Colocation America, Rica Web
})
# Через эти сети ходят люди: iCloud Private Relay (Akamai, Cloudflare, Fastly),
# Cloudflare WARP, Google Fiber.
PEOPLE_ASNS = frozenset({13335, 36183, 54113, 16591})
_HOSTING_NAME = re.compile(
    r"\bhost|h[eé]berg|cloud|server|\bsrv\b|data ?cent|colo(cation)?\b|\bvps\b|dedicated|"
    r"amazon|google(?! fiber)|microsoft|azure|\bovh\b|hetzner|digitalocean|linode|"
    r"vultr|choopa|scaleway|oracle|alibaba|tencent|contabo|leaseweb|m247|datacamp|"
    r"quadranet|psychz|zenlayer|g-core|gcore|selectel|timeweb|aeza|stark industries|"
    r"pq hosting|firstbyte|beget|serverius|ionos|interserver|"
    # VPN и сканеры в сетях, по названию которых хостинг не узнать
    r"vseek|techoff|bucklog|akenai|turunc smart|global connectivity solutions|"
    r"digital transformation plus|gthost|interkvm",
    re.I,
)


class _Reader:
    """Открытая база и её mtime; файл перечитывается, когда его заменили."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reader = None
        self._mtime: Optional[float] = None
        self._checked = 0.0

    def get(self):
        now = time.monotonic()
        if self._checked and now - self._checked < 600:
            return self._reader
        with self._lock:
            self._checked = now
            try:
                mtime = DB_PATH.stat().st_mtime
            except OSError:
                self._reader = None
                return None
            if self._reader is None or mtime != self._mtime:
                try:
                    import maxminddb

                    self._reader = maxminddb.open_database(str(DB_PATH))
                    self._mtime = mtime
                except Exception as e:  # noqa: BLE001 — без базы приём логов не должен падать
                    logger.warning("ASN: не открыть %s: %s", DB_PATH, e)
                    self._reader = None
            return self._reader


_reader = _Reader()


def lookup(ip: Optional[str]) -> Tuple[Optional[int], Optional[str]]:
    """(номер AS, владелец) или (None, None), если адреса или базы нет."""
    if not ip:
        return None, None
    reader = _reader.get()
    if reader is None:
        return None, None
    try:
        rec = reader.get(ip)
    except (ValueError, TypeError):
        return None, None
    if not rec:
        return None, None
    return rec.get("autonomous_system_number"), rec.get("autonomous_system_organization")


def is_hosting(asn: Optional[int], org: Optional[str]) -> bool:
    """Сеть хостинга или облака, а не домашний или мобильный провайдер."""
    if not asn or asn in PEOPLE_ASNS:
        return False
    return asn in HOSTING_ASNS or bool(org and _HOSTING_NAME.search(org))


def download_database() -> dict:
    """Скачать свежую GeoLite2-ASN и атомарно заменить файл."""
    account, key = settings.MAXMIND_ACCOUNT_ID, settings.MAXMIND_LICENSE_KEY
    if not account or not key:
        return {"status": "skipped", "reason": "MAXMIND_ACCOUNT_ID/LICENSE_KEY не заданы"}
    resp = httpx.get(DOWNLOAD_URL, auth=(account, key), follow_redirects=True, timeout=120)
    resp.raise_for_status()
    with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tar:
        member = next(m for m in tar.getmembers() if m.name.endswith(".mmdb"))
        data = tar.extractfile(member).read()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DB_PATH.with_suffix(".mmdb.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, DB_PATH)
    return {"status": "success", "file": str(DB_PATH), "bytes": len(data), "edition": member.name}
