"""Nhận diện sự kiện từ activity_logs, tìm chat nhận và soạn nội dung tin.

Thêm loại sự kiện mới (công việc / yêu cầu / log mới...): thêm giá trị vào NotificationEvent,
hàm nhận diện + hàm tìm người nhận + hàm soạn tin, rồi đăng ký trong producer.
"""

from dataclasses import dataclass
from datetime import datetime
from html import escape

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import ActivityLog, Project, Sprint, WorkItem
from app.models.enums import NotificationEvent

STATUS_LABEL = {
    "backlog": "Backlog",
    "todo": "Cần làm",
    "in_progress": "Đang làm",
    "in_review": "Review",
    "testing": "Kiểm thử",
    "done": "Xong",
    "cancelled": "Huỷ",
}
PRIORITY_LABEL = {
    "critical": "Khẩn cấp",
    "high": "Cao",
    "medium": "Trung bình",
    "low": "Thấp",
    "lowest": "Rất thấp",
}
MAX_LINES = 20  # tin gộp (vd: kết thúc sprint) chỉ liệt kê chừng này công việc


@dataclass(frozen=True)
class StatusChange:
    project_id: int
    item_id: int
    actor_id: int | None
    occurred_at: datetime  # = thời điểm bắt đầu transaction -> các thay đổi cùng lần thao tác có cùng giá trị
    old: str | None
    new: str


def status_change(log: ActivityLog) -> StatusChange | None:
    if log.entity_type != "work_items" or log.action != "status_change" or log.entity_id is None:
        return None
    if log.project_id is None or not log.new_values or "status" not in log.new_values:
        return None
    return StatusChange(
        project_id=log.project_id,
        item_id=log.entity_id,
        actor_id=log.actor_id,
        occurred_at=log.occurred_at,
        old=(log.old_values or {}).get("status"),
        new=log.new_values["status"],
    )


# Group của dự án nhận mọi công việc; chat cá nhân: không báo cho chính người vừa đổi, phải còn quyền xem
# công việc của dự án, scope 'mine' chỉ nhận việc giao cho mình / mình tạo.
_STATUS_RECIPIENTS = text("""
SELECT DISTINCT tc.id
  FROM notification_subscriptions s
  JOIN telegram_chats tc ON tc.id = s.telegram_chat_id AND tc.is_active
 WHERE s.enabled AND s.event = :event
   AND (cardinality(s.statuses) = 0 OR CAST(:status AS text) = ANY (s.statuses))
   AND (
        tc.project_id = :project_id
        OR (tc.user_id IS NOT NULL
            AND tc.user_id IS DISTINCT FROM CAST(:actor_id AS bigint)
            AND (s.scope = 'all' OR tc.user_id IN (:assignee_id, :reporter_id))
            AND fn_user_has_permission(tc.user_id, 'work_item.view', :project_id))
   )
""")


async def status_recipients(db: AsyncSession, change: StatusChange, item: WorkItem) -> list[int]:
    rows = await db.scalars(
        _STATUS_RECIPIENTS,
        {
            "event": NotificationEvent.work_item_status_changed.value,
            "status": change.new,
            "project_id": change.project_id,
            "actor_id": change.actor_id,
            "assignee_id": item.assignee_id or 0,
            "reporter_id": item.reporter_id or 0,
        },
    )
    return list(rows)


@dataclass
class RenderContext:
    projects: dict[int, Project]
    items: dict[int, WorkItem]
    sprints: dict[int, Sprint]
    user_names: dict[int, str]


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _short(title: str, limit: int = 90) -> str:
    return title if len(title) <= limit else title[: limit - 1] + "…"


def _status(value: str | None) -> str:
    return STATUS_LABEL.get(value or "", value or "—")


def item_link(item: WorkItem) -> str:
    page = "board" if item.sprint_id else "backlog"
    return f"{settings.app_public_url.rstrip('/')}/projects/{item.project_id}/{page}?item={item.id}"


def render_status_changes(changes: list[StatusChange], ctx: RenderContext) -> str:
    """Một thay đổi: tin chi tiết. Nhiều thay đổi cùng một lần thao tác (vd: kết thúc sprint): tin gộp."""
    first = changes[0]
    project = ctx.projects[first.project_id]
    actor = ctx.user_names.get(first.actor_id or 0, "Hệ thống")

    if len(changes) == 1:
        item = ctx.items[first.item_id]
        lines = [
            f"🔄 <b>{_e(item.code)}</b> · {_e(_short(item.title))}",
            f"{_e(_status(first.old))} → <b>{_e(_status(first.new))}</b>",
        ]
        who = f"👤 {_e(actor)} đã chuyển"
        if item.assignee_id:
            who += f" · Giao cho: {_e(ctx.user_names.get(item.assignee_id, '—'))}"
        lines.append(who)
        where = f"📁 {_e(project.key)} · {_e(project.name)}"
        if item.sprint_id and item.sprint_id in ctx.sprints:
            where += f" · 🏃 {_e(ctx.sprints[item.sprint_id].name)}"
        where += f" · Ưu tiên: {_e(PRIORITY_LABEL.get(item.priority, item.priority))}"
        lines.append(where)
        lines.append(f'<a href="{_e(item_link(item))}">Mở công việc</a>')
        return "\n".join(lines)

    lines = [f"🔄 <b>{_e(actor)}</b> đã chuyển trạng thái {len(changes)} công việc · 📁 {_e(project.key)}"]
    for c in changes[:MAX_LINES]:
        item = ctx.items[c.item_id]
        lines.append(
            f'• <a href="{_e(item_link(item))}">{_e(item.code)}</a> {_e(_short(item.title, 60))}: '
            f"{_e(_status(c.old))} → <b>{_e(_status(c.new))}</b>"
        )
    if len(changes) > MAX_LINES:
        lines.append(f"… và {len(changes) - MAX_LINES} công việc khác")
    return "\n".join(lines)
