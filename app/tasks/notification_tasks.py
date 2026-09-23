"""Плановые уведомления: сертификаты, всплески атак, пределы панели, неделя.

Переключатели — вкладка «Notifications» в настройках (app/services/notifications.py).
Отбор и тексты — чистые функции ниже, задачи только собирают данные.
"""
import asyncio
import html
import logging
import shutil
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import func, select

from app.core.config import settings
from app.tasks import celery_app
from app.tasks.utils import create_task_db_session

logger = logging.getLogger(__name__)

SSL_WARN_DAYS = 14
# Всплеск: за час заблокировано не меньше SPIKE_MIN и в SPIKE_FACTOR раз больше
# среднего часа прошлых суток (не ниже SPIKE_BASELINE_FLOOR — у тихого сайта
# «в пять раз больше обычного» может значить десяток запросов).
SPIKE_MIN = 200
SPIKE_FACTOR = 5
SPIKE_BASELINE_FLOOR = 20
SECURITY_REPEAT = 6 * 3600
USAGE_REPEAT = 12 * 3600
# Предупреждаем о диске раньше, чем приём логов остановится сам.
DISK_WARN_FACTOR = 1.5


def _run(coro_fn):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro_fn())
    finally:
        loop.close()


async def _redis():
    import redis.asyncio as aioredis

    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


async def _close(client) -> None:
    closer = getattr(client, "aclose", None) or client.close
    await closer()


async def _first_time(key: str, seconds: int) -> bool:
    """True, если об этом ещё не сообщали за ``seconds`` (иначе — молчим)."""
    client = await _redis()
    try:
        return bool(await client.set(key, "1", ex=seconds, nx=True))
    finally:
        await _close(client)


# --- чистые функции ----------------------------------------------------------


def select_expiring(
    certs: Iterable[Tuple[str, str, Optional[datetime]]], now: datetime, days: int = SSL_WARN_DAYS,
) -> List[Tuple[str, datetime]]:
    """Имена, у которых самый свежий выпущенный сертификат кончается в ``days`` дней.

    Продлённый сертификат — новая строка с тем же именем: старую копию, которая
    вот-вот истечёт, пора не считать.
    """
    latest: Dict[str, datetime] = {}
    for _domain, name, not_after in certs:
        if not_after is None:
            continue
        if name not in latest or not_after > latest[name]:
            latest[name] = not_after
    limit = now + timedelta(days=days)
    return sorted(((n, t) for n, t in latest.items() if t < limit), key=lambda x: x[1])


def detect_spikes(
    current: Dict[Any, int], baseline: Dict[Any, int], baseline_hours: int = 24,
) -> List[Tuple[Any, int, float]]:
    """Домены, где за час заблокировано заметно больше обычного: (домен, за час, средний час)."""
    spikes = []
    for key, count in current.items():
        usual = baseline.get(key, 0) / baseline_hours
        if count >= SPIKE_MIN and count >= SPIKE_FACTOR * max(usual, SPIKE_BASELINE_FLOOR):
            spikes.append((key, count, round(usual, 1)))
    return sorted(spikes, key=lambda x: -x[1])


def _num(value: float) -> str:
    return f"{int(value):,}".replace(",", " ")


def _bytes(value: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if value < 1024:
            return f"{value:.0f} {unit}" if unit == "Б" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} ТБ"


def _delta(current: float, previous: float) -> str:
    if not previous:
        return ""
    change = (current - previous) / previous * 100
    return f" ({'+' if change >= 0 else ''}{change:.0f}%)"


def format_weekly(rows: List[Dict[str, Any]], start: datetime, end: datetime) -> str:
    """Текст недельной сводки. ``rows`` — по домену: name, cur, prev (as_dict), visitors."""
    period = f"{start:%d.%m} – {(end - timedelta(days=1)):%d.%m.%Y}"
    total = sum(r["cur"]["total_requests"] for r in rows)
    total_prev = sum(r["prev"]["total_requests"] for r in rows)
    lines = [f"<b>Период:</b> {period} (UTC)",
             f"<b>Запросов всего:</b> {_num(total)}{_delta(total, total_prev)}", ""]
    for r in sorted(rows, key=lambda r: -r["cur"]["total_requests"]):
        cur, prev = r["cur"], r["prev"]
        if not cur["total_requests"] and not prev["total_requests"]:
            continue
        p5 = cur["status_5xx"] / cur["total_requests"] * 100 if cur["total_requests"] else 0
        parts = [
            f"{_num(cur['total_requests'])} запр.{_delta(cur['total_requests'], prev['total_requests'])}",
            f"{_num(r['visitors'])} посет.",
            f"кэш {cur['cache_hit_ratio']:.0f}%",
            _bytes(cur["total_bandwidth"]),
        ]
        if cur["threats_blocked"]:
            parts.append(f"блок {_num(cur['threats_blocked'])}")
        if p5 >= 1:
            parts.append(f"⚠️ 5xx {p5:.1f}%")
        lines.append(f"<b>{html.escape(r['name'])}</b>: " + ", ".join(parts))
    return "\n".join(lines)


# --- задачи ------------------------------------------------------------------


@celery_app.task(name="app.tasks.notify.ssl_expiry")
def ssl_expiry():
    return _run(_ssl_expiry)


async def _ssl_expiry():
    from app.models.certificate import Certificate, CertificateStatus
    from app.models.domain import Domain
    from app.services import notifications
    from app.services.alert_service import AlertLevel, AlertService

    if not (await notifications.load()).get("ssl", True):
        return {"skipped": "off"}
    now = datetime.utcnow()
    engine, session_factory = create_task_db_session()
    try:
        async with session_factory() as db:
            rows = (await db.execute(
                select(Domain.name, Certificate.common_name, Certificate.not_after)
                .join(Domain, Domain.id == Certificate.domain_id)
                .where(Certificate.status == CertificateStatus.ISSUED, Domain.status == "active")
            )).all()
    finally:
        await engine.dispose()
    expiring = select_expiring(rows, now)
    if not expiring:
        return {"expiring": 0}
    lines = []
    for name, not_after in expiring:
        days = (not_after - now).days
        state = "истёк" if not_after < now else f"через {days} дн."
        lines.append(f"• <b>{html.escape(name)}</b> — {not_after:%d.%m.%Y} ({state})")
    await AlertService.send_alert(
        title="Сертификаты скоро истекают",
        message="\n".join(lines) + "\n\nАвтопродление их не обновило — проверьте домены в панели.",
        level=AlertLevel.WARNING, category="ssl", event="ssl_expiry",
    )
    return {"expiring": len(expiring)}


@celery_app.task(name="app.tasks.notify.security_spikes")
def security_spikes():
    return _run(_security_spikes)


async def _security_spikes():
    from app.models.domain import Domain
    from app.models.log import RequestLog
    from app.services import notifications
    from app.services.alert_service import AlertLevel, AlertService
    from app.services.analytics_query import Window, floor, totals

    if not (await notifications.load()).get("security", True):
        return {"skipped": "off"}
    hour = floor(datetime.utcnow(), "hour")
    last = Window("1h", hour - timedelta(hours=1), hour, "hour")
    day = Window("24h", hour - timedelta(hours=25), hour - timedelta(hours=1), "hour")
    engine, session_factory = create_task_db_session()
    try:
        async with session_factory() as db:
            def blocked(metrics):
                return {k: m.as_dict()["threats_blocked"] + m.as_dict()["rate_limited"]
                        for k, m in metrics.items() if k is not None}

            spikes = detect_spikes(
                blocked(await totals(db, last, group_by="domain")),
                blocked(await totals(db, day, group_by="domain")),
            )
            if not spikes:
                return {"spikes": 0}
            names = dict((await db.execute(select(Domain.id, Domain.name))).all())
            lines = []
            for domain_id, count, usual in spikes:
                if not await _first_time(f"notify:security:{domain_id}", SECURITY_REPEAT):
                    continue
                top = (await db.execute(
                    select(RequestLog.client_ip, func.count().label("n"))
                    .where(RequestLog.domain_id == domain_id,
                           RequestLog.timestamp >= last.start, RequestLog.timestamp < last.end,
                           (RequestLog.waf_status.in_(("blocked", "challenged"))) | (RequestLog.status_code == 429))
                    .group_by(RequestLog.client_ip).order_by(func.count().desc()).limit(3)
                )).all()
                sources = ", ".join(f"{ip} ({n})" for ip, n in top)
                lines.append(
                    f"• <b>{html.escape(names.get(domain_id, str(domain_id)))}</b>: {_num(count)} за час "
                    f"(обычно ~{usual:g}/ч)" + (f"\n  чаще всего: {sources}" if sources else "")
                )
    finally:
        await engine.dispose()
    if lines:
        await AlertService.send_alert(
            title="Всплеск заблокированных запросов",
            message="\n".join(lines) + f"\n\nЧас {last.start:%H:%M}–{last.end:%H:%M} UTC. "
                    "Подробности — Analytics → Security в панели.",
            level=AlertLevel.WARNING, category="security", event="security_spike",
        )
    return {"spikes": len(lines)}


@celery_app.task(name="app.tasks.notify.usage")
def usage():
    return _run(_usage)


async def _usage():
    from app.services import notifications
    from app.services.alert_service import AlertLevel, AlertService

    if not (await notifications.load()).get("usage", True):
        return {"skipped": "off"}
    problems = []
    free_gb = shutil.disk_usage("/").free / 1024 ** 3
    limit_gb = settings.RAW_LOGS_MIN_FREE_DISK_GB
    if free_gb < limit_gb * DISK_WARN_FACTOR and await _first_time("notify:usage:disk", USAGE_REPEAT):
        stopped = free_gb < limit_gb
        problems.append(
            f"• Свободно на диске панели {free_gb:.1f} ГБ (порог {limit_gb:.0f} ГБ) — "
            + ("приём сырых логов остановлен." if stopped else "скоро приём сырых логов остановится.")
        )
    prev_hour = datetime.utcnow() - timedelta(hours=1)
    client = await _redis()
    try:
        dropped = int(await client.get(f"analytics:dropped:{prev_hour:%Y%m%d%H}") or 0)
    finally:
        await _close(client)
    if dropped and await _first_time("notify:usage:raw_logs", USAGE_REPEAT):
        problems.append(
            f"• За час отброшено {_num(dropped)} строк логов: предел "
            f"{_num(settings.RAW_LOGS_MAX_PER_HOUR)} строк в час (RAW_LOGS_MAX_PER_HOUR). "
            "Итоги аналитики за этот час неполные."
        )
    if problems:
        await AlertService.send_alert(
            title="Панель CDN упирается в пределы",
            message="\n".join(problems),
            level=AlertLevel.WARNING, category="usage", event="usage",
        )
    return {"problems": len(problems), "free_gb": round(free_gb, 1), "dropped": dropped}


@celery_app.task(name="app.tasks.notify.weekly_report")
def weekly_report():
    return _run(_weekly_report)


async def _weekly_report():
    from app.models.domain import Domain
    from app.services import notifications
    from app.services.alert_service import AlertLevel, AlertService
    from app.services.analytics_query import Metrics, Window, floor, totals, unique_visitors

    if not (await notifications.load()).get("weekly", True):
        return {"skipped": "off"}
    end = floor(datetime.utcnow(), "day")
    cur_w = Window("7d", end - timedelta(days=7), end, "day")
    prev_w = cur_w.previous()
    engine, session_factory = create_task_db_session()
    try:
        async with session_factory() as db:
            domains = (await db.execute(
                select(Domain.id, Domain.name).where(Domain.status == "active")
            )).all()
            cur = await totals(db, cur_w, group_by="domain")
            prev = await totals(db, prev_w, group_by="domain")
            rows = []
            for domain_id, name in domains:
                rows.append({
                    "name": name,
                    "cur": cur.get(domain_id, Metrics()).as_dict(),
                    "prev": prev.get(domain_id, Metrics()).as_dict(),
                    "visitors": await unique_visitors(db, cur_w, [domain_id]),
                })
    finally:
        await engine.dispose()
    await AlertService.send_alert(
        title="Неделя в CDN",
        message=format_weekly(rows, cur_w.start, cur_w.end),
        level=AlertLevel.INFO, category="weekly", event="weekly_report",
    )
    return {"domains": len(rows)}
