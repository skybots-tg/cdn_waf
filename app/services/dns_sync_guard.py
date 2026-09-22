"""Защита DNS-нод от пустого или урезанного снапшота.

Панель шлёт на ноды полный снапшот, нода делает TRUNCATE и заливает его заново.
Пустой или обрезанный снапшот (баг, полувосстановленная БД панели, пустой ответ
Postgres в момент сбоя) стёр бы зоны на всех нодах за секунды — все домены
клиентов перестали бы резолвиться разом. Такой снапшот отвергаем: нода сверяет
его со своей БД, панель — с последним снапшотом, который приняла нода. Применить
его всё равно можно только явным force.

Модуль без зависимостей: его импортирует и панель, и dns_server на нодах.
"""
from dataclasses import dataclass
from typing import Optional

# Доля, на которую число доменов или записей может сократиться за один синк.
# Каждое удаление в панели сразу запускает синк, так что за раз уходит домен-
# другой; больше половины разом — почти всегда авария, а не действие админа.
SYNC_MAX_SHRINK_SHARE = 0.5


@dataclass(frozen=True)
class SnapshotCounts:
    domains: int
    records: int

    def as_dict(self) -> dict:
        return {"domains": self.domains, "records": self.records}

    @classmethod
    def from_dict(cls, data: dict) -> "SnapshotCounts":
        return cls(domains=int(data["domains"]), records=int(data["records"]))


def payload_counts(payload) -> SnapshotCounts:
    """Размер снапшота DNSSyncPayload."""
    return SnapshotCounts(domains=len(payload.domains), records=len(payload.records))


def snapshot_problem(incoming: SnapshotCounts, current: SnapshotCounts) -> Optional[str]:
    """Почему снапшот incoming нельзя применить поверх current; None — можно."""
    checks = (
        ("доменов", incoming.domains, current.domains),
        ("DNS-записей", incoming.records, current.records),
    )
    for label, new, old in checks:
        if old == 0:
            continue  # первый синк или пустая база: сравнивать не с чем
        if new == 0:
            return f"в снапшоте 0 {label}, было {old}"
        if new < old * (1 - SYNC_MAX_SHRINK_SHARE):
            lost = round((old - new) * 100 / old)
            limit = round(SYNC_MAX_SHRINK_SHARE * 100)
            return f"{label} в снапшоте {new} вместо {old} (−{lost}%, порог {limit}%)"
    return None
