"""Cấu hình thông báo Telegram: chat cá nhân (/me/telegram) và group của dự án (/projects/{id}/telegram)."""

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ProjectContext, get_current_user, require_project_permission
from app.db.session import get_db
from app.models import NotificationSubscription, TelegramChat, TelegramLinkCode, User
from app.models.enums import NotificationEvent, NotificationScope
from app.schemas.notification import (
    MyTelegramOut,
    ProjectTelegramOut,
    SubscriptionOut,
    SubscriptionUpdate,
    TelegramChatOut,
    TelegramLinkOut,
)
from app.services.common import not_found
from app.services.notifications import telegram

router = APIRouter()
me_router = APIRouter()

LINK_TTL = timedelta(minutes=15)
MANAGE = "project.notification.manage"


def _require_configured() -> None:
    if not telegram.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chưa cấu hình bot Telegram trên máy chủ (TELEGRAM_BOT_TOKEN)",
        )


async def _bot_username() -> str:
    try:
        return await telegram.bot_username()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Không kết nối được Telegram") from exc


async def _new_link(db: AsyncSession, user: User, project_id: int | None) -> TelegramLinkOut:
    _require_configured()
    username = await _bot_username()
    link = TelegramLinkCode(
        code=secrets.token_urlsafe(24),
        kind="project" if project_id else "user",
        user_id=user.id,
        project_id=project_id,
        expires_at=datetime.now(UTC) + LINK_TTL,
    )
    db.add(link)
    await db.commit()
    # ?start=: mở chat riêng với bot; ?startgroup=: chọn group để thêm bot vào. Telegram gửi "/start <mã>" cho bot.
    param = "startgroup" if project_id else "start"
    return TelegramLinkOut(url=f"https://t.me/{username}?{param}={link.code}", expires_at=link.expires_at)


async def _chat_out(db: AsyncSession, chats: list[TelegramChat]) -> list[TelegramChatOut]:
    subs = await db.scalars(
        select(NotificationSubscription)
        .where(NotificationSubscription.telegram_chat_id.in_([c.id for c in chats]))
        .order_by(NotificationSubscription.id)
    )
    by_chat: dict[int, list[SubscriptionOut]] = {}
    for s in subs:
        by_chat.setdefault(s.telegram_chat_id, []).append(SubscriptionOut.model_validate(s))
    return [
        TelegramChatOut.model_validate(c).model_copy(update={"subscriptions": by_chat.get(c.id, [])}) for c in chats
    ]


async def _set_subscription(
    db: AsyncSession, chat: TelegramChat, event: NotificationEvent, body: SubscriptionUpdate
) -> SubscriptionOut:
    sub = await db.scalar(
        select(NotificationSubscription).where(
            NotificationSubscription.telegram_chat_id == chat.id, NotificationSubscription.event == event
        )
    )
    if sub is None:
        sub = NotificationSubscription(telegram_chat_id=chat.id, event=event)
        db.add(sub)
    sub.enabled = body.enabled
    # Group nhận mọi công việc của dự án; 'mine' chỉ có nghĩa với chat cá nhân
    sub.scope = body.scope if chat.user_id else NotificationScope.all
    sub.statuses = list(dict.fromkeys(body.statuses))
    await db.commit()
    return SubscriptionOut.model_validate(sub)


async def _send_test(db: AsyncSession, chat: TelegramChat, html: str) -> None:
    _require_configured()
    try:
        await telegram.send_message(chat.chat_id, html)
    except telegram.TelegramError as exc:
        if exc.chat_unreachable:
            chat.is_active = False
            await db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Telegram: {exc.description}") from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Không kết nối được Telegram") from exc
    if not chat.is_active:  # gửi lại được (vd: người dùng bỏ chặn bot) -> bật lại
        chat.is_active = True
        await db.commit()


# ----------------------------------------------------------------------------- cá nhân


async def _my_chat(db: AsyncSession, user: User) -> TelegramChat:
    chat = await db.scalar(select(TelegramChat).where(TelegramChat.user_id == user.id))
    if chat is None:
        raise not_found("kết nối Telegram")
    return chat


@me_router.get("/telegram", response_model=MyTelegramOut, summary="Kết nối Telegram của tôi")
async def get_my_telegram(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    chat = await db.scalar(select(TelegramChat).where(TelegramChat.user_id == user.id))
    return MyTelegramOut(configured=telegram.is_configured(), chat=(await _chat_out(db, [chat]))[0] if chat else None)


@me_router.post("/telegram/link", response_model=TelegramLinkOut, summary="Tạo link kết nối Telegram cá nhân")
async def link_my_telegram(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _new_link(db, user, None)


@me_router.put(
    "/telegram/subscriptions/{event}", response_model=SubscriptionOut, summary="Tuỳ chọn nhận thông báo của tôi"
)
async def update_my_subscription(
    event: NotificationEvent,
    body: SubscriptionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _set_subscription(db, await _my_chat(db, user), event, body)


@me_router.post("/telegram/test", status_code=status.HTTP_204_NO_CONTENT, summary="Gửi tin thử tới Telegram của tôi")
async def test_my_telegram(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _send_test(db, await _my_chat(db, user), "🔔 Tin thử: bạn sẽ nhận thông báo công việc tại đây.")


@me_router.delete("/telegram", status_code=status.HTTP_204_NO_CONTENT, summary="Ngắt kết nối Telegram của tôi")
async def unlink_my_telegram(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.delete(await _my_chat(db, user))
    await db.commit()


# ----------------------------------------------------------------------------- group của dự án


async def _project_chat(db: AsyncSession, project_id: int, chat_id: int) -> TelegramChat:
    chat = await db.get(TelegramChat, chat_id)
    if chat is None or chat.project_id != project_id:
        raise not_found("group Telegram")
    return chat


@router.get("", response_model=ProjectTelegramOut, summary="Các group Telegram nhận thông báo của dự án")
async def list_project_chats(
    ctx: ProjectContext = Depends(require_project_permission(MANAGE)), db: AsyncSession = Depends(get_db)
):
    chats = list(
        await db.scalars(
            select(TelegramChat).where(TelegramChat.project_id == ctx.project.id).order_by(TelegramChat.linked_at)
        )
    )
    return ProjectTelegramOut(configured=telegram.is_configured(), chats=await _chat_out(db, chats))


@router.post("/link", response_model=TelegramLinkOut, summary="Tạo link thêm bot vào group Telegram")
async def link_project_chat(
    ctx: ProjectContext = Depends(require_project_permission(MANAGE)), db: AsyncSession = Depends(get_db)
):
    return await _new_link(db, ctx.user, ctx.project.id)


@router.put("/chats/{chat_id}/subscriptions/{event}", response_model=SubscriptionOut, summary="Bộ lọc thông báo")
async def update_project_subscription(
    chat_id: int,
    event: NotificationEvent,
    body: SubscriptionUpdate,
    ctx: ProjectContext = Depends(require_project_permission(MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    return await _set_subscription(db, await _project_chat(db, ctx.project.id, chat_id), event, body)


@router.post("/chats/{chat_id}/test", status_code=status.HTTP_204_NO_CONTENT, summary="Gửi tin thử tới group")
async def test_project_chat(
    chat_id: int,
    ctx: ProjectContext = Depends(require_project_permission(MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    chat = await _project_chat(db, ctx.project.id, chat_id)
    await _send_test(db, chat, f"🔔 Tin thử: group sẽ nhận thông báo của dự án <b>{ctx.project.key}</b>.")


@router.delete("/chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Gỡ group khỏi dự án")
async def delete_project_chat(
    chat_id: int,
    ctx: ProjectContext = Depends(require_project_permission(MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    await db.delete(await _project_chat(db, ctx.project.id, chat_id))
    await db.commit()
