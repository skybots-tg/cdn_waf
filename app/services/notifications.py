"""Уведомления как у Cloudflare: какие слать и куда ещё, кроме Telegram.

Категории — переключатели вкладки «Notifications» в настройках панели:

* ``security`` — всплеск заблокированных WAF и ограниченных запросов у домена;
* ``downtime`` — origin сайта упал или вернулся;
* ``ssl`` — сертификат истекает в ближайшие дни и не продлён;
* ``usage`` — пределы самой панели: бюджет сырых логов за час и место на диске;
* ``weekly`` — сводка за неделю по понедельникам.

Оповещения о нодах CDN и DNS идут всегда: их выключение прятало бы аварию
самой CDN. Настройки читаются с кэшем на минуту; БД недоступна — всё включено.
"""
import html
import ipaddress
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

CATEGORIES = ("security", "downtime", "ssl", "usage", "weekly")
MAX_WEBHOOKS = 5
_TTL = 60.0
_cache: Dict[str, Any] = {"at": 0.0, "value": None}


def defaults() -> Dict[str, Any]:
    return {**{c: True for c in CATEGORIES}, "webhooks": []}


def validate_webhook_url(url: str) -> str:
    """Только https и публичный адрес: панель не должна стучаться внутрь сети."""
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("webhook must be an https:// URL")
    if len(url) > 500:
        raise ValueError("webhook URL is too long")
    host = parsed.hostname.lower()
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        raise ValueError("webhook must point to a public host")
    if ip is not None and not ip.is_global:
        raise ValueError("webhook must point to a public host")
    return url


def parse_webhooks(raw: Optional[str]) -> List[Dict[str, str]]:
    try:
        items = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    hooks = []
    for item in items if isinstance(items, list) else []:
        url = item.get("url") if isinstance(item, dict) else None
        try:
            hooks.append({"url": validate_webhook_url(url)})
        except ValueError:
            continue
    return hooks[:MAX_WEBHOOKS]


def row_to_dict(row) -> Dict[str, Any]:
    if row is None:
        return defaults()
    data = {c: bool(getattr(row, c)) for c in CATEGORIES}
    data["webhooks"] = parse_webhooks(row.webhooks)
    return data


async def load(fresh: bool = False) -> Dict[str, Any]:
    now = time.monotonic()
    if not fresh and _cache["value"] is not None and now - _cache["at"] < _TTL:
        return _cache["value"]
    try:
        from app.models.notification import NotificationSettings
        from app.tasks.utils import create_task_db_session

        engine, session_factory = create_task_db_session()
        try:
            async with session_factory() as db:
                value = row_to_dict(await db.get(NotificationSettings, 1))
        finally:
            await engine.dispose()
    except Exception as exc:  # noqa: BLE001 — без настроек оповещение важнее тишины
        logger.warning("Notification settings unavailable, sending everything: %s", exc)
        value = defaults()
    _cache.update(at=now, value=value)
    return value


def invalidate() -> None:
    _cache["value"] = None


def plain_text(markup: str) -> str:
    """Текст Telegram-разметки без тегов — для вебхуков."""
    text = re.sub(r"<br\s*/?>", "\n", markup or "")
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


async def post_webhooks(
    hooks: List[Dict[str, str]], *, title: str, message: str, level: str, event: Optional[str],
) -> int:
    """Отправить оповещение на вебхуки. Тело понимают Slack (text) и Discord (content)."""
    if not hooks:
        return 0
    body = plain_text(f"<b>{title}</b>\n\n{message}")
    payload = {
        "text": body,
        "content": body[:1900],
        "title": plain_text(title),
        "level": level,
        "event": event,
    }
    delivered = 0
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        for hook in hooks:
            try:
                resp = await client.post(hook["url"], json=payload)
                if resp.status_code < 300:
                    delivered += 1
                else:
                    logger.warning("Webhook %s answered %s", urlparse(hook["url"]).hostname, resp.status_code)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Webhook %s failed: %s", urlparse(hook["url"]).hostname, exc)
    return delivered
