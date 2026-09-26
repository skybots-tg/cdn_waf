"""Разный ответ DNS для России и остального мира.

Зачем. Все ноды CDN стоят в России, а российские провайдеры режут трафик из сетей
Telegram: робот, который строит превью ссылок, с 03.09.2026 не доходит ни до
одной ноды — ссылка на сайт в Telegram приходит без картинки. До origin в Вене
он доходит. Поэтому для имён из ``GEO_SPLIT_NAMES`` российским клиентам отдаём
ноды, как всем раньше, а остальному миру — собственный адрес записи (origin).

Где клиент. Если резолвер прислал EDNS Client Subnet (Google Public DNS и
другие публичные) — по подсети клиента, иначе по адресу самого резолвера:
провайдерский резолвер стоит там же, где его абоненты. Страна — по таблице
российских сетей ``data/ru_nets.txt.gz`` (та же, что у nutrition-ai-bot,
``shared/data/ru_nets.txt.gz``; формат: «4|6 начало конец» в hex).

Не уверены — отвечаем по-старому, нодами: адрес не разобрался, приватный,
таблица не загрузилась. Ошибиться в сторону нод безопасно, это прежнее
поведение.

ECS в ответе обязателен: без него резолвер считает ответ годным для всех своих
клиентов (RFC 7871, scope 0), и Google раздал бы «венский» адрес всей России.
Отвечаем с областью, равной присланной подсети.

Имена задаёт переменная окружения ``GEO_SPLIT_NAMES`` (через запятую, полные
имена, без точки в конце). Пусто — поведение DNS не меняется ни для кого.
"""
from __future__ import annotations

import bisect
import gzip
import ipaddress
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dnslib import QTYPE, EDNS0, EDNSOption

logger = logging.getLogger("dns_server.geo_split")

ECS_CODE = 8
_DATA = Path(__file__).resolve().parent.parent / "data" / "ru_nets.txt.gz"
#: Меньше — таблица обрезана или собрана с ошибкой (в сентябре 2026 их 7394).
_MIN_V4_RANGES = 1000

_nets: dict[int, tuple[list[int], list[int]]] = {}
_tried = False


def names() -> frozenset[str]:
    raw = os.environ.get("GEO_SPLIT_NAMES", "")
    return frozenset(n.strip().lower().rstrip(".") for n in raw.split(",") if n.strip())


def _load() -> dict[int, tuple[list[int], list[int]]]:
    starts: dict[int, list[int]] = {4: [], 6: []}
    ends: dict[int, list[int]] = {4: [], 6: []}
    try:
        with gzip.open(_DATA, "rt", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("#"):
                    continue
                kind, start, end = line.split()
                starts[int(kind)].append(int(start, 16))
                ends[int(kind)].append(int(end, 16))
    except Exception as exc:  # noqa: BLE001 — без таблицы просто отвечаем нодами
        logger.warning("geo split: не прочитать %s: %s", _DATA, exc)
        return {}
    if len(starts[4]) < _MIN_V4_RANGES:
        logger.error("geo split: таблица %s подозрительно мала (IPv4 %d)", _DATA.name, len(starts[4]))
        return {}
    logger.info("geo split: сети РФ IPv4 %d, IPv6 %d", len(starts[4]), len(starts[6]))
    return {v: (starts[v], ends[v]) for v in (4, 6)}


def warm() -> None:
    global _nets, _tried
    if not _tried:
        _tried = True
        _nets = _load()


def is_russia(ip: Optional[str]) -> Optional[bool]:
    """Российский ли адрес; ``None`` — не знаем (не разобрался, приватный, нет таблицы)."""
    warm()
    if not _nets:
        return None
    try:
        addr = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return None
    if addr.version == 6 and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_unspecified:
        return None
    starts, ends = _nets[addr.version]
    i = bisect.bisect_right(starts, int(addr)) - 1
    return i >= 0 and int(addr) <= ends[i]


@dataclass
class Ecs:
    family: int
    source: int
    address: str

    def reply_option(self, scope: Optional[int] = None) -> EDNSOption:
        """ECS для ответа. Область по умолчанию — вся присланная подсеть;
        0 — ответ от подсети не зависел и годится всем клиентам резолвера."""
        scope = self.source if scope is None else scope
        packed = ipaddress.ip_address(self.address).packed[: (self.source + 7) // 8]
        return EDNSOption(ECS_CODE, self.family.to_bytes(2, "big") + bytes([self.source, scope]) + packed)


def parse_ecs(request) -> Optional[Ecs]:
    """EDNS Client Subnet из запроса или ``None``."""
    for rr in request.ar:
        if rr.rtype != QTYPE.OPT:
            continue
        for opt in rr.rdata or []:
            if getattr(opt, "code", None) != ECS_CODE:
                continue
            data = bytes(opt.data)
            if len(data) < 4:
                return None
            family, source = int.from_bytes(data[:2], "big"), data[2]
            raw = data[4:]
            size = {1: 4, 2: 16}.get(family)
            if size is None or len(raw) > size or source > size * 8:
                return None
            try:
                address = str(ipaddress.ip_address(raw.ljust(size, b"\0")))
            except ValueError:
                return None
            return Ecs(family, source, address)
    return None


@dataclass
class Decision:
    russia: bool          # отдавать ноды (True) или origin (False)
    ecs: Optional[Ecs]    # ECS запроса — вернуть в ответе с областью


def decide(name: str, request, client_ip: Optional[str]) -> Optional[Decision]:
    """Решение для имени; ``None`` — имя не делится, отвечать как всегда."""
    if name not in names():
        return None
    ecs = None
    try:
        ecs = parse_ecs(request)
    except Exception:  # noqa: BLE001 — кривой OPT не должен ронять ответ
        logger.warning("geo split: не разобрать ECS для %s", name, exc_info=True)
    where = ecs.address if ecs is not None and ecs.source > 0 else client_ip
    ru = is_russia(where)
    decision = Decision(russia=ru is not False, ecs=ecs)
    logger.info("  geo split: %s от %s (%s) -> %s", name, where, "ecs" if ecs else "резолвер",
                "ноды" if decision.russia else "origin")
    return decision


def echo_ecs(request, reply) -> None:
    """На любой запрос с ECS — ECS в ответе, с областью 0 (RFC 7871).

    Так резолвер видит, что сервер понимает подсеть клиента. Google Public DNS
    шлёт ECS только тем серверам, которых сам распознал как понимающих: пока мы
    отвечали без ECS, он спрашивал без подсети, и россиянам с 8.8.8.8
    доставался зарубежный ответ. Область 0 значит «годится всем» — для имён,
    которые не делятся, так и есть, кэш резолвера это не портит.
    """
    if any(rr.rtype == QTYPE.OPT for rr in reply.ar):
        return
    try:
        ecs = parse_ecs(request)
    except Exception:  # noqa: BLE001
        return
    if ecs is not None:
        reply.add_ar(EDNS0(udp_len=1232, opts=[ecs.reply_option(scope=0)]))


def add_ecs(reply, decision: Optional[Decision]) -> None:
    """Вернуть ECS в ответе, если ответ зависел от подсети клиента."""
    if decision is None or decision.ecs is None:
        return
    reply.add_ar(EDNS0(udp_len=1232, opts=[decision.ecs.reply_option()]))
