"""Настройки уведомлений (вкладка «Notifications») и пробная отправка.

Канал оповещений у установки один (Telegram-чат из .env плюс вебхуки), поэтому
менять настройки может только суперпользователь.
"""
import json
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_superuser
from app.models.notification import NotificationSettings
from app.services import notifications
from app.services.alert_service import AlertLevel, AlertService

router = APIRouter()


class NotificationSettingsIn(BaseModel):
    security: bool = True
    downtime: bool = True
    ssl: bool = True
    usage: bool = True
    weekly: bool = True
    webhooks: List[str] = Field(default_factory=list, max_length=notifications.MAX_WEBHOOKS)

    @field_validator("webhooks")
    @classmethod
    def _v_webhooks(cls, urls):
        cleaned = []
        for url in urls:
            url = notifications.validate_webhook_url(url)
            if url not in cleaned:
                cleaned.append(url)
        return cleaned


def _out(data: dict) -> dict:
    return {
        **{c: data[c] for c in notifications.CATEGORIES},
        "webhooks": [h["url"] for h in data["webhooks"]],
        "telegram_configured": AlertService._is_configured(),
    }


@router.get("/settings")
async def get_settings(db: AsyncSession = Depends(get_db), _user=Depends(get_current_superuser)):
    return _out(notifications.row_to_dict(await db.get(NotificationSettings, 1)))


@router.put("/settings")
async def save_settings(
    data: NotificationSettingsIn,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_superuser),
):
    row = await db.get(NotificationSettings, 1)
    if row is None:
        row = NotificationSettings(id=1)
        db.add(row)
    for category in notifications.CATEGORIES:
        setattr(row, category, getattr(data, category))
    row.webhooks = json.dumps([{"url": url} for url in data.webhooks])
    row.updated_at = datetime.utcnow()
    await db.commit()
    notifications.invalidate()
    return _out(notifications.row_to_dict(row))


@router.post("/test")
async def send_test(db: AsyncSession = Depends(get_db), _user=Depends(get_current_superuser)):
    """Пробное оповещение во все каналы, независимо от переключателей."""
    data = notifications.row_to_dict(await db.get(NotificationSettings, 1))
    title = "Проверка уведомлений FlareCloud"
    message = "Так будут выглядеть оповещения панели. Этот канал подключён."
    telegram = await AlertService.send_telegram(f"ℹ️ <b>{title}</b>\n\n{message}")
    delivered = await notifications.post_webhooks(
        data["webhooks"], title=title, message=message, level=AlertLevel.INFO.value, event="test",
    )
    if not telegram and not delivered:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Ни один канал не принял сообщение: проверьте Telegram в .env и адреса вебхуков",
        )
    return {"telegram": telegram, "webhooks_delivered": delivered, "webhooks_total": len(data["webhooks"])}
