"""Telegram alert service for node health monitoring"""
import logging
from enum import Enum
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


class AlertLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


LEVEL_EMOJI = {
    AlertLevel.INFO: "\u2139\ufe0f",
    AlertLevel.WARNING: "\u26a0\ufe0f",
    AlertLevel.CRITICAL: "\U0001f6a8",
}


class AlertService:
    """Send operational alerts to Telegram"""

    @staticmethod
    def _is_configured() -> bool:
        return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)

    @staticmethod
    async def send_telegram(text: str, parse_mode: str = "HTML") -> bool:
        if not AlertService._is_configured():
            logger.debug("Telegram alerts not configured, skipping")
            return False

        url = f"{TELEGRAM_API}/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": settings.TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": parse_mode,
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code != 200:
                    logger.error("Telegram API error %s: %s", resp.status_code, resp.text)
                    return False
                return True
        except Exception as exc:
            logger.error("Failed to send Telegram alert: %s", exc)
            return False

    @staticmethod
    def _user_mention() -> str:
        uid = settings.TELEGRAM_ALERT_USER_ID
        if uid:
            return f'\n\n<a href="tg://user?id={uid}">&#8252; Требуется внимание</a>'
        return ""

    @staticmethod
    async def send_alert(
        title: str,
        message: str,
        level: AlertLevel = AlertLevel.WARNING,
        tag_user: bool = False,
    ) -> bool:
        emoji = LEVEL_EMOJI.get(level, "")
        text = f"{emoji} <b>{title}</b>\n\n{message}"
        if tag_user:
            text += AlertService._user_mention()
        return await AlertService.send_telegram(text)

    # ---- convenience shortcuts ----

    @staticmethod
    async def origin_down(
        origin_name: str,
        origin_host: str,
        domain_name: str,
        consecutive_failures: int,
    ):
        await AlertService.send_alert(
            title="Origin недоступен",
            message=(
                f"<b>Origin:</b> {origin_name} ({origin_host})\n"
                f"<b>Домен:</b> {domain_name}\n"
                f"<b>Ошибок подряд:</b> {consecutive_failures}\n\n"
                "Origin выведен из ротации."
            ),
            level=AlertLevel.WARNING,
        )

    @staticmethod
    async def origin_recovered(
        origin_name: str,
        origin_host: str,
        domain_name: str,
    ):
        await AlertService.send_alert(
            title="Origin восстановлен",
            message=(
                f"<b>Origin:</b> {origin_name} ({origin_host})\n"
                f"<b>Домен:</b> {domain_name}\n\n"
                "Origin снова в ротации."
            ),
            level=AlertLevel.INFO,
        )

    @staticmethod
    async def all_origins_down(domain_name: str, kept_origin: Optional[str] = None):
        msg = (
            f"<b>Домен:</b> {domain_name}\n\n"
            "Все origins не отвечают!"
        )
        if kept_origin:
            msg += f"\nОставлен последний origin: <b>{kept_origin}</b>"
        await AlertService.send_alert(
            title="ВСЕ ORIGINS НЕДОСТУПНЫ",
            message=msg,
            level=AlertLevel.CRITICAL,
            tag_user=True,
        )

    @staticmethod
    async def prolonged_outage(
        domain_name: str,
        duration_minutes: int,
        unhealthy_origins: int,
        total_origins: int,
    ):
        await AlertService.send_alert(
            title="Длительный сбой origins",
            message=(
                f"<b>Домен:</b> {domain_name}\n"
                f"<b>Длительность:</b> {duration_minutes} мин\n"
                f"<b>Недоступно:</b> {unhealthy_origins}/{total_origins} origins\n\n"
                "Проблема сохраняется продолжительное время."
            ),
            level=AlertLevel.CRITICAL,
            tag_user=True,
        )

    # ---- edge / DNS node alerts ----

    @staticmethod
    async def edge_node_down(node_name: str, ip: str, reason: str):
        await AlertService.send_alert(
            title="Edge-нода недоступна",
            message=(
                f"<b>Нода:</b> {node_name} ({ip})\n"
                f"<b>Причина:</b> {reason}"
            ),
            level=AlertLevel.WARNING,
        )

    @staticmethod
    async def edge_node_recovered(node_name: str, ip: str):
        await AlertService.send_alert(
            title="Edge-нода восстановлена",
            message=(
                f"<b>Нода:</b> {node_name} ({ip})\n\n"
                "Нода снова отвечает. Включение в ротацию — вручную."
            ),
            level=AlertLevel.INFO,
        )

    @staticmethod
    async def edge_node_disabled(node_name: str, ip: str, reason: str):
        await AlertService.send_alert(
            title="Edge-нода ОТКЛЮЧЕНА автоматически",
            message=(
                f"<b>Нода:</b> {node_name} ({ip})\n"
                f"<b>Причина:</b> {reason}\n\n"
                "Нода снята с балансировки, DNS sync запущен."
            ),
            level=AlertLevel.CRITICAL,
            tag_user=True,
        )

    @staticmethod
    async def dns_node_down(node_name: str, ip: str):
        await AlertService.send_alert(
            title="DNS-нода недоступна",
            message=(
                f"<b>Нода:</b> {node_name} ({ip})\n\n"
                "DNS-сервер не отвечает на health check."
            ),
            level=AlertLevel.CRITICAL,
            tag_user=True,
        )

    @staticmethod
    async def dns_node_recovered(node_name: str, ip: str):
        await AlertService.send_alert(
            title="DNS-нода восстановлена",
            message=f"<b>Нода:</b> {node_name} ({ip})",
            level=AlertLevel.INFO,
        )
