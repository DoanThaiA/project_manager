from datetime import datetime

from pydantic import BaseModel

from app.models.enums import NotificationEvent, NotificationScope, WorkItemStatus
from app.schemas.common import ORMModel


class SubscriptionOut(ORMModel):
    event: NotificationEvent
    scope: NotificationScope
    statuses: list[WorkItemStatus]
    enabled: bool


class SubscriptionUpdate(BaseModel):
    enabled: bool = True
    scope: NotificationScope = NotificationScope.all
    statuses: list[WorkItemStatus] = []  # rỗng = mọi trạng thái


class TelegramChatOut(ORMModel):
    id: int
    type: str
    title: str | None
    is_active: bool
    linked_at: datetime
    subscriptions: list[SubscriptionOut] = []


class TelegramLinkOut(BaseModel):
    url: str
    expires_at: datetime


class MyTelegramOut(BaseModel):
    configured: bool  # máy chủ đã đặt TELEGRAM_BOT_TOKEN
    chat: TelegramChatOut | None


class ProjectTelegramOut(BaseModel):
    configured: bool
    chats: list[TelegramChatOut]
