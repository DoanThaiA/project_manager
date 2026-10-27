"""Lấy sự kiện trong hàng đợi notification_events -> tạo tin cần gửi (notification_deliveries)."""

from collections import defaultdict

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityLog, NotificationDelivery, Project, Sprint, User, WorkItem
from app.models.enums import NotificationEvent
from app.services.notifications.events import (
    RenderContext,
    StatusChange,
    render_status_changes,
    status_change,
    status_recipients,
)

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
    changes = [c for log in logs if (c := status_change(log))]
    if changes:
        await _enqueue_status_changes(db, changes)
    await db.commit()
    return len(log_ids)


async def _enqueue_status_changes(db: AsyncSession, changes: list[StatusChange]) -> None:
    items = {w.id: w for w in await db.scalars(select(WorkItem).where(WorkItem.id.in_({c.item_id for c in changes})))}
    changes = [c for c in changes if c.item_id in items and items[c.item_id].deleted_at is None]
    if not changes:
        return

    # Gộp các thay đổi trong cùng một lần thao tác (cùng transaction: cùng người, cùng thời điểm bắt đầu)
    groups: dict[tuple, list[StatusChange]] = defaultdict(list)
    for c in changes:
        groups[(c.project_id, c.actor_id, c.occurred_at)].append(c)

    per_message: list[tuple[int, list[StatusChange]]] = []
    for group in groups.values():
        by_chat: dict[int, list[StatusChange]] = defaultdict(list)
        for c in group:
            for chat_id in await status_recipients(db, c, items[c.item_id]):
                by_chat[chat_id].append(c)
        per_message.extend(by_chat.items())
    if not per_message:
        return

    sprint_ids = {w.sprint_id for w in items.values() if w.sprint_id}
    user_ids = {c.actor_id for c in changes if c.actor_id} | {uid for w in items.values() for uid in w.assignee_ids}
    ctx = RenderContext(
        projects={
            p.id: p for p in await db.scalars(select(Project).where(Project.id.in_({c.project_id for c in changes})))
        },
        items=items,
        sprints={s.id: s for s in await db.scalars(select(Sprint).where(Sprint.id.in_(sprint_ids)))},
        user_names={
            uid: name for uid, name in await db.execute(select(User.id, User.full_name).where(User.id.in_(user_ids)))
        },
    )
    for chat_id, chat_changes in per_message:
        db.add(
            NotificationDelivery(
                telegram_chat_id=chat_id,
                event=NotificationEvent.work_item_status_changed,
                text=render_status_changes(chat_changes, ctx),
            )
        )
