"""Gửi các tin đang chờ trong notification_deliveries tới Telegram."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NotificationDelivery, TelegramChat
from app.services.notifications import telegram

logger = logging.getLogger(__name__)

RETRY_DELAYS = [30, 120, 600, 1800, 3600]  # giây, sau lần lỗi thứ 1, 2, ...; hết danh sách thì bỏ


async def send_due(db: AsyncSession, limit: int = 20) -> int:
    """Gửi một lô tin đến hạn; trả về số tin đã xử lý (0 = không còn tin đến hạn)."""
    now = datetime.now(UTC)
    deliveries = list(
        await db.scalars(
            select(NotificationDelivery)
            .where(NotificationDelivery.status == "pending", NotificationDelivery.next_try_at <= now)
            .order_by(NotificationDelivery.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    if not deliveries:
        await db.rollback()
        return 0
    chats = {
        c.id: c
        for c in await db.scalars(
            select(TelegramChat).where(TelegramChat.id.in_({d.telegram_chat_id for d in deliveries}))
        )
    }
    for d in deliveries:
        await _send_one(db, d, chats[d.telegram_chat_id])
        await asyncio.sleep(0.05)  # giới hạn chung của Telegram ~30 tin/giây
    await db.commit()
    return len(deliveries)


async def _send_one(db: AsyncSession, d: NotificationDelivery, chat: TelegramChat) -> None:
    now = datetime.now(UTC)
    if not chat.is_active:
        d.status, d.error = "failed", "Chat đã ngừng nhận thông báo"
        return
    try:
        await telegram.send_message(chat.chat_id, d.text)
    except telegram.TelegramError as exc:
        if exc.migrate_to_chat_id:  # group nâng cấp thành supergroup -> đổi chat_id, gửi lại ngay
            await migrate_chat(db, chat.chat_id, exc.migrate_to_chat_id)
            d.next_try_at = now
        elif exc.retry_after:  # bị giới hạn tốc độ: chờ đúng thời gian Telegram yêu cầu, không tính là lỗi
            d.next_try_at = now + timedelta(seconds=exc.retry_after)
        elif exc.chat_unreachable:
            chat.is_active = False
            d.status, d.error = "failed", exc.description
        else:
            _retry_later(d, str(exc), now)
    except httpx.HTTPError as exc:
        _retry_later(d, f"{type(exc).__name__}: {exc}", now)
    else:
        d.status, d.sent_at, d.error = "sent", now, None


def _retry_later(d: NotificationDelivery, error: str, now: datetime) -> None:
    d.attempts += 1
    d.error = error[:1000]
    if d.attempts > len(RETRY_DELAYS):
        d.status = "failed"
        logger.warning("Bỏ tin Telegram %s sau %s lần lỗi: %s", d.id, d.attempts, error)
    else:
        d.next_try_at = now + timedelta(seconds=RETRY_DELAYS[d.attempts - 1])


async def migrate_chat(db: AsyncSession, old_chat_id: int, new_chat_id: int) -> None:
    await db.execute(update(TelegramChat).where(TelegramChat.chat_id == old_chat_id).values(chat_id=new_chat_id))
