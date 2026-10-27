"""Xử lý tin bot nhận được: /start <mã> để liên kết chat, bot bị đuổi khỏi group, group đổi chat_id."""

import logging
import re
from datetime import UTC, datetime
from html import escape as _e

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NotificationSubscription, Project, TelegramChat, TelegramLinkCode, User
from app.models.enums import NotificationEvent, NotificationScope
from app.services.notifications import telegram
from app.services.notifications.events import DEFAULT_GROUP, DEFAULT_PERSONAL
from app.services.notifications.sender import migrate_chat

logger = logging.getLogger(__name__)

# Trong group lệnh có thể kèm tên bot: /start@ten_bot <mã>
START_RE = re.compile(r"^/start(?:@\w+)?(?:\s+([A-Za-z0-9_-]+))?\s*$")

HELP = (
    "Xin chào! Bot gửi thông báo từ hệ thống quản lý dự án.\n"
    "• Nhận thông báo cá nhân: trong app, mở <b>Thông báo của tôi</b> › <b>Kết nối Telegram</b>.\n"
    "• Nhận thông báo cho group: trong app, mở dự án › <b>Thông báo</b> › <b>Thêm group Telegram</b>."
)


async def handle_update(db: AsyncSession, upd: dict) -> None:
    if member := upd.get("my_chat_member"):
        # Bot bị xoá khỏi group / người dùng chặn bot -> ngừng gửi
        if member.get("new_chat_member", {}).get("status") in ("left", "kicked"):
            await db.execute(
                update(TelegramChat).where(TelegramChat.chat_id == member["chat"]["id"]).values(is_active=False)
            )
            await db.commit()
        return

    msg = upd.get("message")
    if not msg:
        return
    if new_id := msg.get("migrate_to_chat_id"):
        await migrate_chat(db, msg["chat"]["id"], new_id)
        await db.commit()
        return
    if m := START_RE.match(msg.get("text") or ""):
        reply = await link_chat(db, msg["chat"], m.group(1)) if m.group(1) else HELP
        await _reply(msg["chat"]["id"], reply)


async def link_chat(db: AsyncSession, chat: dict, code: str) -> str:
    """Liên kết chat theo mã; trả về câu trả lời gửi lại cho người dùng."""
    now = datetime.now(UTC)
    link = await db.get(TelegramLinkCode, code, with_for_update=True)
    if link is None or link.used_at is not None or link.expires_at < now:
        return "❌ Mã liên kết không hợp lệ hoặc đã hết hạn. Hãy tạo liên kết mới trong app."

    chat_id, chat_type = chat["id"], chat["type"]
    if link.kind == "user":
        if chat_type != "private":
            return "❌ Liên kết này dùng để nhận thông báo cá nhân — hãy mở link trong chat riêng với bot."
        user = await db.get(User, link.user_id)
        # Một tài khoản Telegram chỉ gắn với một người dùng và ngược lại
        await db.execute(
            delete(TelegramChat).where(
                TelegramChat.user_id.is_not(None), TelegramChat.chat_id == chat_id, TelegramChat.user_id != link.user_id
            )
        )
        row = await db.scalar(select(TelegramChat).where(TelegramChat.user_id == link.user_id))
        title = " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])) or chat.get("username")
        if chat.get("username"):
            title = f"{title} (@{chat['username']})"
        row = await _upsert(db, row, chat_id, chat_type, title, link, user_id=link.user_id)
        await _ensure_subscriptions(db, row.id, DEFAULT_PERSONAL, NotificationScope.mine)
        reply = (
            f"✅ Đã kết nối Telegram với tài khoản <b>{_e(user.full_name if user else '')}</b>.\n"
            "Bạn sẽ nhận thông báo khi được giao việc, khi công việc / yêu cầu của bạn đổi trạng thái, "
            "có log công việc hoặc bình luận mới. Đổi tuỳ chọn trong app › Thông báo của tôi."
        )
    else:
        if chat_type == "private":
            return "❌ Liên kết này dùng để thêm bot vào group — hãy mở link và chọn một group."
        project = await db.get(Project, link.project_id)
        if project is None or project.deleted_at is not None:
            return "❌ Dự án không còn tồn tại."
        row = await db.scalar(
            select(TelegramChat).where(TelegramChat.project_id == link.project_id, TelegramChat.chat_id == chat_id)
        )
        row = await _upsert(db, row, chat_id, chat_type, chat.get("title"), link, project_id=link.project_id)
        await _ensure_subscriptions(db, row.id, DEFAULT_GROUP, NotificationScope.all)
        reply = (
            f"✅ Group sẽ nhận thông báo của dự án <b>{_e(project.key)} · {_e(project.name)}</b>: "
            "công việc, giao việc, log công việc, yêu cầu khách hàng, bình luận và sprint."
        )
    link.used_at = now
    await db.commit()
    return reply


async def _upsert(db, row, chat_id, chat_type, title, link, **owner) -> TelegramChat:
    if row is None:
        row = TelegramChat(**owner)
        db.add(row)
    row.chat_id, row.type, row.title = chat_id, chat_type, (title or "")[:255] or None
    row.is_active, row.linked_by, row.linked_at = True, link.user_id, datetime.now(UTC)
    await db.flush()
    return row


async def _ensure_subscriptions(
    db: AsyncSession, chat_pk: int, events: list[NotificationEvent], scope: NotificationScope
) -> None:
    """Chat mới liên kết: bật các thông báo mặc định (giữ nguyên tuỳ chọn đã có nếu liên kết lại)."""
    existing = set(
        await db.scalars(
            select(NotificationSubscription.event).where(NotificationSubscription.telegram_chat_id == chat_pk)
        )
    )
    for event in events:
        if event not in existing:
            db.add(NotificationSubscription(telegram_chat_id=chat_pk, event=event, scope=scope, statuses=[]))


async def _reply(chat_id: int, html: str) -> None:
    try:
        await telegram.send_message(chat_id, html)
    except Exception:  # trả lời không được thì thôi, liên kết vẫn đã lưu
        logger.exception("Không trả lời được chat Telegram %s", chat_id)
