"""Какие уведомления слать: переключатели вкладки «Notifications» в настройках.

Канал оповещений у установки один — чат из TELEGRAM_CHAT_ID (плюс вебхуки
отсюда), поэтому и настройки одни: строка с id=1. Её нет — всё включено.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, Text

from app.core.database import Base


class NotificationSettings(Base):
    __tablename__ = "notification_settings"

    id = Column(Integer, primary_key=True)
    security = Column(Boolean, default=True, nullable=False)
    downtime = Column(Boolean, default=True, nullable=False)
    ssl = Column(Boolean, default=True, nullable=False)
    usage = Column(Boolean, default=True, nullable=False)
    weekly = Column(Boolean, default=True, nullable=False)
    webhooks = Column(Text, nullable=True)  # JSON: [{"url": "https://…"}]
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
