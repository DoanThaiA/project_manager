"""Tác vụ nền trong tiến trình API: xử lý hàng đợi + gửi tin, và nhận tin của bot (long polling)."""

import asyncio
import logging
import time

import httpx
from sqlalchemy import text

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.services.notifications import telegram
from app.services.notifications.bot import handle_update
from app.services.notifications.producer import produce
from app.services.notifications.sender import send_due

logger = logging.getLogger(__name__)

_CLEANUP = [
    "DELETE FROM notification_deliveries WHERE status <> 'pending' AND created_at < now() - interval '30 days'",
    "DELETE FROM telegram_link_codes WHERE expires_at < now() - interval '1 day'",
]


async def queue_loop() -> None:
    last_cleanup = 0.0
    while True:
        try:
            async with AsyncSessionLocal() as db:
                while await produce(db):
                    pass
                while await send_due(db):
                    pass
                if time.monotonic() - last_cleanup > 3600:
                    for sql in _CLEANUP:
                        await db.execute(text(sql))
                    await db.commit()
                    last_cleanup = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Lỗi xử lý hàng đợi thông báo")
        await asyncio.sleep(settings.telegram_poll_seconds)


async def bot_loop() -> None:
    offset: int | None = None
    while True:
        try:
            await telegram.call("deleteWebhook")  # long polling không chạy được khi bot đang đặt webhook
            break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Không kết nối được Telegram, thử lại sau")
            await asyncio.sleep(30)
    while True:
        try:
            updates = await telegram.get_updates(offset)
        except asyncio.CancelledError:
            raise
        except telegram.TelegramError as exc:
            # 409: một tiến trình khác đang nhận tin của cùng bot
            logger.warning("getUpdates lỗi: %s", exc)
            await asyncio.sleep(30 if exc.status == 409 else 5)
            continue
        except httpx.HTTPError as exc:
            logger.warning("getUpdates lỗi mạng: %s", exc)
            await asyncio.sleep(5)
            continue
        for upd in updates:
            offset = upd["update_id"] + 1
            try:
                async with AsyncSessionLocal() as db:
                    await handle_update(db, upd)
            except Exception:
                logger.exception("Lỗi xử lý tin Telegram %s", upd.get("update_id"))


class NotificationWorker:
    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        if not telegram.is_configured():
            logger.info("Chưa đặt TELEGRAM_BOT_TOKEN — tắt thông báo Telegram")
            return
        self._tasks = [asyncio.create_task(queue_loop()), asyncio.create_task(bot_loop())]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []


worker = NotificationWorker()
