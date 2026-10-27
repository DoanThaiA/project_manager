"""Lấy sự kiện trong hàng đợi notification_events -> tạo tin cần gửi (notification_deliveries)."""

from collections import defaultdict

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ActivityLog,
    NotificationDelivery,
    NotificationSubscription,
    Project,
    Requirement,
    RequirementComment,
    Sprint,
    TelegramChat,
    User,
    WorkItem,
    WorkLog,
)
from app.models.enums import NotificationEvent
from app.services.notifications.events import SPECS, Event, RenderContext, detect, recipients, render

E = NotificationEvent

# Lấy và xoá khỏi hàng đợi trong cùng transaction với việc tạo tin: lỗi giữa chừng thì rollback, không mất sự kiện.
# SKIP LOCKED: nhiều worker chạy song song không lấy trùng.
_TAKE = text("""
DELETE FROM notification_events
 WHERE id IN (SELECT id FROM notification_events ORDER BY id LIMIT :limit FOR UPDATE SKIP LOCKED)
RETURNING activity_log_id
""")


async def produce(db: AsyncSession, limit: int = 200) -> int:
    """Xử lý một lô sự kiện; trả về số sự kiện đã lấy (0 = hàng đợi trống)."""
    log_ids = list(await db.scalars(_TAKE, {"limit": limit}))
    if not log_ids:
        await db.rollback()
        return 0
    logs = await db.scalars(select(ActivityLog).where(ActivityLog.id.in_(log_ids)).order_by(ActivityLog.id))
    events = [ev for log in logs for ev in detect(log)]
    if events:
        await _enqueue(db, events)
    await db.commit()
    return len(log_ids)


async def _by_id(db: AsyncSession, model, ids: set[int]) -> dict:
    ids.discard(None)
    if not ids:
        return {}
    return {row.id: row for row in await db.scalars(select(model).where(model.id.in_(ids)))}


async def _load_context(db: AsyncSession, events: list[Event]) -> RenderContext:
    ids: dict[NotificationEvent, set[int]] = defaultdict(set)
    for ev in events:
        ids[ev.kind].add(ev.entity_id)
    ctx = RenderContext()
    ctx.work_logs = await _by_id(db, WorkLog, set(ids[E.work_log_created]))
    ctx.comments = await _by_id(db, RequirementComment, set(ids[E.requirement_commented]))

    item_ids = ids[E.work_item_status_changed] | ids[E.work_item_created] | ids[E.work_item_assigned]
    item_ids |= {log.work_item_id for log in ctx.work_logs.values() if log.work_item_id}
    ctx.items = await _by_id(db, WorkItem, set(item_ids))
    # Công việc cha của subtask mới (hiện "Subtask của ...")
    parents = {w.parent_id for w in ctx.items.values() if w.parent_id and w.parent_id not in ctx.items}
    ctx.items |= await _by_id(db, WorkItem, parents)

    req_ids = ids[E.requirement_created] | ids[E.requirement_status_changed]
    req_ids |= {c.requirement_id for c in ctx.comments.values()}
    req_ids |= {log.requirement_id for log in ctx.work_logs.values() if log.requirement_id}
    ctx.requirements = await _by_id(db, Requirement, set(req_ids))
    if ctx.comments:
        rows = await db.execute(
            select(RequirementComment.requirement_id, RequirementComment.user_id).where(
                RequirementComment.requirement_id.in_({c.requirement_id for c in ctx.comments.values()}),
                RequirementComment.deleted_at.is_(None),
                RequirementComment.user_id.is_not(None),
            )
        )
        for req_id, user_id in rows:
            ctx.commenters.setdefault(req_id, set()).add(user_id)

    sprint_ids = set(ids[E.sprint_status_changed]) | {w.sprint_id for w in ctx.items.values() if w.sprint_id}
    ctx.sprints = await _by_id(db, Sprint, sprint_ids)

    project_ids = {ev.project_id for ev in events if ev.project_id}
    project_ids |= {r.project_id for r in ctx.requirements.values()}
    ctx.projects = await _by_id(db, Project, project_ids)

    user_ids = {ev.actor_id for ev in events if ev.actor_id}
    user_ids |= {uid for w in ctx.items.values() for uid in w.assignee_ids}
    user_ids |= {log.user_id for log in ctx.work_logs.values()}
    user_ids |= {c.user_id for c in ctx.comments.values() if c.user_id}
    user_ids |= {r.assignee_id for r in ctx.requirements.values() if r.assignee_id}
    if user_ids:
        rows = await db.execute(select(User.id, User.full_name).where(User.id.in_(user_ids)))
        ctx.user_names = dict(rows.all())
    return ctx


async def _assigned_subscribers(db: AsyncSession, user_ids: set[int]) -> set[int]:
    """Người (trong user_ids) đang nhận tin "được giao việc" ở chat cá nhân."""
    if not user_ids:
        return set()
    rows = await db.scalars(
        select(TelegramChat.user_id)
        .join(NotificationSubscription, NotificationSubscription.telegram_chat_id == TelegramChat.id)
        .where(
            TelegramChat.user_id.in_(user_ids),
            TelegramChat.is_active,
            NotificationSubscription.event == E.work_item_assigned,
            NotificationSubscription.enabled,
        )
    )
    return set(rows)


async def _enqueue(db: AsyncSession, events: list[Event]) -> None:
    ctx = await _load_context(db, events)
    # Bình luận: activity log không có project_id -> lấy theo yêu cầu
    events = [
        ev.with_project(ctx.requirements[ctx.comments[ev.entity_id].requirement_id].project_id)
        if ev.kind == E.requirement_commented and ev.entity_id in ctx.comments
        else ev
        for ev in events
    ]
    events = [ev for ev in events if ev.project_id in ctx.projects and SPECS[ev.kind].entity(ev, ctx) is not None]
    if not events:
        return

    # Người được giao ngay khi tạo công việc đã nhận tin "giao việc" -> không gửi thêm tin "tạo công việc"
    assigned_on_create = await _assigned_subscribers(
        db,
        {uid for ev in events if ev.kind == E.work_item_created for uid in ctx.items[ev.entity_id].assignee_ids},
    )

    # Gộp các sự kiện cùng loại trong cùng một lần thao tác (cùng transaction: cùng người, cùng thời điểm bắt đầu)
    groups: dict[tuple, list[Event]] = defaultdict(list)
    for ev in events:
        groups[(ev.kind, ev.project_id, ev.actor_id, ev.occurred_at)].append(ev)

    for (kind, *_), group in groups.items():
        by_chat: dict[int, list[Event]] = defaultdict(list)
        for ev in group:
            skip = (
                set(ctx.items[ev.entity_id].assignee_ids) & assigned_on_create if kind == E.work_item_created else set()
            )
            for chat_id in await recipients(db, ev, ctx, skip):
                by_chat[chat_id].append(ev)
        for chat_id, chat_events in by_chat.items():
            db.add(NotificationDelivery(telegram_chat_id=chat_id, event=kind, text=render(chat_events, ctx)))
