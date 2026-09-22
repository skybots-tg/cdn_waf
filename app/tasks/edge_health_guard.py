"""Защита автоотключения edge-нод от сбоев на стороне проверяющего.

Все проверки edge-нод идут из одной точки — Celery на панели. Когда сломалось
что-то у самой панели (пропал интернет или маршрут до хостеров, лёг cdn_app
и heartbeat'ы не доходят, истёк сертификат у домена из общей TLS-выборки),
мёртвыми выглядят сразу все ноды. Выключи мы их — dns_server отдаст для
проксируемых доменов origin-записи: трафик пойдёт мимо CDN/WAF, а адреса
origin'ов утекут наружу.

Здесь только решения и проба связности; сами проверки нод — в
edge_health_tasks.
"""
import asyncio

EDGE_MIN_ENABLED_NODES = 2  # never auto-disable below this count
# Доля упавших за один раунд, выше которой не верим проверке: ноды стоят у
# разных хостеров и одновременно ложатся редко, а сбой у панели бьёт по всем.
EDGE_MASS_FAILURE_SHARE = 0.5
CONTROL_PROBE_TIMEOUT = 4
# Адреса вне нашей инфраструктуры и без DNS: резолвер панели тоже может лечь.
CONTROL_PROBE_TARGETS = (
    ("77.88.8.8", 53),  # Яндекс DNS
    ("1.1.1.1", 443),  # Cloudflare
    ("8.8.8.8", 443),  # Google
)


def can_auto_disable(enabled_count: int) -> bool:
    """Можно ли выключить ещё одну ноду, не опустившись ниже минимума."""
    return enabled_count > EDGE_MIN_ENABLED_NODES


def is_mass_failure(failing: int, total: int) -> bool:
    """Больше половины нод упало за раунд — вероятнее, сломалась сама проверка."""
    return total > 0 and failing > total * EDGE_MASS_FAILURE_SHARE


async def checker_is_online(
    targets: tuple[tuple[str, int], ...] = CONTROL_PROBE_TARGETS,
    timeout: float = CONTROL_PROBE_TIMEOUT,
) -> bool:
    """Видит ли панель интернет: достаточно одного ответившего адреса."""
    results = await asyncio.gather(
        *(_tcp_reachable(host, port, timeout) for host, port in targets)
    )
    return any(results)


async def _tcp_reachable(host: str, port: int, timeout: float) -> bool:
    writer = None
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        return True
    except Exception:
        return False
    finally:
        if writer is not None:
            writer.close()
