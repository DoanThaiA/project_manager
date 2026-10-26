"""Tác vụ nền trong tiến trình API: xử lý hàng đợi + gửi tin, và nhận tin của bot (long polling)."""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.services.notifications import telegram
from app.services.notifications.bot import handle_update
from app.services.notifications.producer import produce
from app.services.notifications.sender import send_due

logger = logging.getLogger(__name__)


@dataclass
class BotStatus:
    """Tình trạng nhận lệnh của bot trong tiến trình này — hiện trên trang cấu hình để dễ chẩn đoán."""

    running: bool = False
    last_poll_at: datetime | None = None  # lần gần nhất getUpdates trả về thành công
    error: str | None = None  # lỗi gần nhất (đã hết lỗi thì None)


status = BotStatus()

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
    status.running = True
    while True:
        try:
            await telegram.call("deleteWebhook")  # long polling không chạy được khi bot đang đặt webhook
            logger.info("Bot Telegram @%s bắt đầu nhận lệnh (long polling)", await telegram.bot_username())
            break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            status.error = f"Không kết nối được Telegram: {exc}"
            logger.exception("Không kết nối được Telegram, thử lại sau")
            await asyncio.sleep(30)
    while True:
        try:
            updates = await telegram.get_updates(offset)
        except asyncio.CancelledError:
            raise
        except telegram.TelegramError as exc:
            # 409: một nơi khác (bot / webhook / server khác) đang nhận tin của cùng token
            status.error = (
                "Một chương trình khác đang dùng cùng token bot (Telegram báo 409 Conflict)"
                if exc.status == 409
                else str(exc)
            )
            logger.warning("getUpdates lỗi: %s", exc)
            await asyncio.sleep(30 if exc.status == 409 else 5)
            continue
        except Exception as exc:
            status.error = f"Lỗi kết nối Telegram: {type(exc).__name__}: {exc}"
            logger.warning("getUpdates lỗi: %s", status.error)
            await asyncio.sleep(5)
            continue
        status.last_poll_at, status.error = datetime.now(UTC), None
        for upd in updates:
            offset = upd["update_id"] + 1
            logger.info("Telegram: nhận update %s", _describe(upd))
            try:
                async with AsyncSessionLocal() as db:
                    await handle_update(db, upd)
            except Exception:
                logger.exception("Lỗi xử lý tin Telegram %s", upd.get("update_id"))


def _describe(upd: dict) -> str:
    if msg := upd.get("message"):
        return f"tin từ chat {msg['chat']['id']} ({msg['chat']['type']}): {(msg.get('text') or '')[:20]!r}"
    if member := upd.get("my_chat_member"):
        return f"bot {member.get('new_chat_member', {}).get('status')} ở chat {member['chat']['id']}"
    return str(list(upd))


def _log_crash(task: asyncio.Task) -> None:
    if not task.cancelled() and (exc := task.exception()):
        status.running = False
        status.error = f"Tác vụ nền dừng vì lỗi: {exc}"
        logger.error("Tác vụ thông báo Telegram dừng", exc_info=exc)


class NotificationWorker:
    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        if not telegram.is_configured():
            logger.info("Chưa đặt TELEGRAM_BOT_TOKEN — tắt thông báo Telegram")
            return
        self._tasks = [asyncio.create_task(queue_loop()), asyncio.create_task(bot_loop())]
        for task in self._tasks:
            task.add_done_callback(_log_crash)

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        status.running = False


worker = NotificationWorker()
