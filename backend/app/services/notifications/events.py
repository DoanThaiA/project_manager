"""Nhận diện sự kiện từ activity_logs, tìm chat nhận và soạn nội dung tin.

Thêm loại sự kiện mới: thêm giá trị vào NotificationEvent, nhận diện trong `detect`, khai báo một `Spec`
(quyền xem, người "của tôi", lọc trạng thái, cách soạn tin) trong SPECS, nạp dữ liệu cần thiết trong producer.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from html import escape
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import ActivityLog, Project, Requirement, RequirementComment, Sprint, WorkItem, WorkLog
from app.models.enums import (
    NotificationEvent,
    NotificationScope,
    RequirementStatus,
    SprintStatus,
    WorkItemStatus,
)

E = NotificationEvent

STATUS_LABEL = {
    "backlog": "Backlog",
    "todo": "Cần làm",
    "in_progress": "Đang làm",
    "in_review": "Review",
    "testing": "Kiểm thử",
    "done": "Xong",
    "cancelled": "Huỷ",
}
REQUIREMENT_STATUS_LABEL = {
    "new": "Mới",
    "analyzing": "Đang phân tích",
    "pending_approval": "Chờ duyệt",
    "approved": "Đã duyệt",
    "rejected": "Từ chối",
    "in_progress": "Đang thực hiện",
    "done": "Hoàn thành",
    "closed": "Đã đóng",
    "cancelled": "Huỷ",
}
SPRINT_VERB = {
    "planned": "chuyển về kế hoạch",
    "active": "bắt đầu",
    "completed": "kết thúc",
    "cancelled": "huỷ",
}
PRIORITY_LABEL = {
    "critical": "Khẩn cấp",
    "high": "Cao",
    "medium": "Trung bình",
    "low": "Thấp",
    "lowest": "Rất thấp",
}
WORK_ITEM_TYPE_LABEL = {"epic": "Epic", "story": "Story", "task": "Task", "bug": "Bug", "subtask": "Subtask"}
REQUIREMENT_TYPE_LABEL = {
    "feature": "Tính năng",
    "change_request": "Thay đổi",
    "bug": "Lỗi",
    "improvement": "Cải tiến",
    "support": "Hỗ trợ",
    "other": "Khác",
}
ACTIVITY_LABEL = {
    "analysis": "Phân tích",
    "design": "Thiết kế",
    "development": "Lập trình",
    "testing": "Kiểm thử",
    "review": "Review",
    "meeting": "Họp",
    "deployment": "Triển khai",
    "support": "Hỗ trợ",
    "documentation": "Tài liệu",
    "other": "Khác",
}
MAX_LINES = 20  # tin gộp (vd: kết thúc sprint) chỉ liệt kê chừng này mục
MAX_TEXT = 300  # nội dung log / bình luận trích trong tin

# Dòng dấu ảnh / file trong văn bản ([Ảnh: ...], [Ảnh lỗi: ...], [File: ...]) — khớp frontend text-images.tsx
_MARKER_RE = re.compile(r"^\[(Ảnh[^:\]]*|File): [^\]]+\]$")


@dataclass(frozen=True)
class Event:
    kind: NotificationEvent
    project_id: int | None  # bình luận yêu cầu: activity log không có project_id, producer điền theo yêu cầu
    entity_id: int
    actor_id: int | None
    occurred_at: datetime  # = thời điểm bắt đầu transaction -> các thay đổi cùng lần thao tác có cùng giá trị
    old: dict = field(default_factory=dict, hash=False, compare=False)
    new: dict = field(default_factory=dict, hash=False, compare=False)

    def with_project(self, project_id: int) -> "Event":
        return Event(self.kind, project_id, self.entity_id, self.actor_id, self.occurred_at, self.old, self.new)


def detect(log: ActivityLog) -> list[Event]:
    """Các sự kiện cần báo trong một dòng activity_logs (có thể nhiều: vừa đổi trạng thái vừa giao việc)."""
    if log.entity_id is None:
        return []
    old, new = log.old_values or {}, log.new_values or {}

    def ev(kind: NotificationEvent) -> Event:
        return Event(kind, log.project_id, log.entity_id, log.actor_id, log.occurred_at, old, new)

    match log.entity_type, log.action:
        case "work_items", "create":
            events = [ev(E.work_item_created)]
            if new.get("assignee_ids"):
                events.append(ev(E.work_item_assigned))
            return events
        case "work_items", "update" | "status_change":
            events = [ev(E.work_item_status_changed)] if log.action == "status_change" and "status" in new else []
            if set(new.get("assignee_ids") or []) - set(old.get("assignee_ids") or []):
                events.append(ev(E.work_item_assigned))
            return events
        case "work_logs", "create":
            return [ev(E.work_log_created)]
        case "requirements", "create":
            return [ev(E.requirement_created)]
        case "requirements", "status_change" if "status" in new:
            return [ev(E.requirement_status_changed)]
        case "requirement_comments", "create":
            return [ev(E.requirement_commented)]
        case "sprints", "status_change" if "status" in new:
            return [ev(E.sprint_status_changed)]
    return []


@dataclass
class RenderContext:
    projects: dict[int, Project] = field(default_factory=dict)
    items: dict[int, WorkItem] = field(default_factory=dict)
    requirements: dict[int, Requirement] = field(default_factory=dict)
    comments: dict[int, RequirementComment] = field(default_factory=dict)
    commenters: dict[int, set[int]] = field(default_factory=dict)  # requirement_id -> người đã bình luận
    work_logs: dict[int, WorkLog] = field(default_factory=dict)
    sprints: dict[int, Sprint] = field(default_factory=dict)
    user_names: dict[int, str] = field(default_factory=dict)

    def user(self, user_id: int | None, default: str = "—") -> str:
        return self.user_names.get(user_id or 0, default)

    def users(self, user_ids: list[int]) -> str:
        return ", ".join(self.user(uid) for uid in user_ids)


# ----------------------------------------------------------------------------- tiện ích soạn tin


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _short(title: str, limit: int = 90) -> str:
    return title if len(title) <= limit else title[: limit - 1] + "…"


def _plain(content: str | None, limit: int = MAX_TEXT) -> str:
    """Bỏ dòng dấu ảnh / file, rút gọn."""
    lines = [line for line in (content or "").splitlines() if not _MARKER_RE.match(line.strip())]
    return _short("\n".join(lines).strip(), limit)


def _status(value: str | None) -> str:
    return STATUS_LABEL.get(value or "", value or "—")


def _req_status(value: str | None) -> str:
    return REQUIREMENT_STATUS_LABEL.get(value or "", value or "—")


def _hours(value: Any) -> str:
    return f"{float(Decimal(str(value))):g}h"


def _date(value: Any) -> str:
    d = value if isinstance(value, date) else date.fromisoformat(str(value))
    return d.strftime("%d/%m/%Y")


def _url(path: str) -> str:
    return f"{settings.app_public_url.rstrip('/')}{path}"


def item_link(item: WorkItem) -> str:
    page = "board" if item.sprint_id else "backlog"
    return _url(f"/projects/{item.project_id}/{page}?item={item.id}")


def requirement_link(req: Requirement) -> str:
    return _url(f"/projects/{req.project_id}/requirements/{req.id}")


def _where(ctx: RenderContext, project_id: int, sprint_id: int | None = None, priority: str | None = None) -> str:
    project = ctx.projects[project_id]
    where = f"📁 {_e(project.key)} · {_e(project.name)}"
    if sprint_id and sprint_id in ctx.sprints:
        where += f" · 🏃 {_e(ctx.sprints[sprint_id].name)}"
    if priority:
        where += f" · Ưu tiên: {_e(PRIORITY_LABEL.get(priority, priority))}"
    return where


def _item_ref(item: WorkItem, limit: int = 60) -> str:
    return f'<a href="{_e(item_link(item))}">{_e(item.code)}</a> {_e(_short(item.title, limit))}'


def _req_ref(req: Requirement, limit: int = 60) -> str:
    return f'<a href="{_e(requirement_link(req))}">{_e(req.code)}</a> {_e(_short(req.title, limit))}'


def _added_assignees(ev: Event) -> list[int]:
    before = set(ev.old.get("assignee_ids") or [])
    return [uid for uid in ev.new.get("assignee_ids") or [] if uid not in before]


# ----------------------------------------------------------------------------- công việc


def _one_status(ev: Event, ctx: RenderContext) -> str:
    item = ctx.items[ev.entity_id]
    who = f"👤 {_e(ctx.user(ev.actor_id, 'Hệ thống'))} đã chuyển"
    if item.assignee_ids:
        who += f" · Giao cho: {_e(ctx.users(item.assignee_ids))}"
    return "\n".join(
        [
            f"🔄 <b>{_e(item.code)}</b> · {_e(_short(item.title))}",
            f"{_e(_status(ev.old.get('status')))} → <b>{_e(_status(ev.new['status']))}</b>",
            who,
            _where(ctx, item.project_id, item.sprint_id, item.priority),
            f'<a href="{_e(item_link(item))}">Mở công việc</a>',
        ]
    )


def _line_status(ev: Event, ctx: RenderContext) -> str:
    item = ctx.items[ev.entity_id]
    return f"• {_item_ref(item)}: {_e(_status(ev.old.get('status')))} → <b>{_e(_status(ev.new['status']))}</b>"


def _one_created(ev: Event, ctx: RenderContext) -> str:
    item = ctx.items[ev.entity_id]
    who = f"👤 {_e(ctx.user(ev.actor_id, 'Hệ thống'))} đã tạo · {_e(WORK_ITEM_TYPE_LABEL.get(item.type, item.type))}"
    if item.assignee_ids:
        who += f" · Giao cho: {_e(ctx.users(item.assignee_ids))}"
    lines = [f"🆕 <b>{_e(item.code)}</b> · {_e(_short(item.title))}", who]
    if item.parent_id and item.parent_id in ctx.items:
        lines.append(f"↳ Subtask của {_item_ref(ctx.items[item.parent_id])}")
    lines += [
        _where(ctx, item.project_id, item.sprint_id, item.priority),
        f'<a href="{_e(item_link(item))}">Mở công việc</a>',
    ]
    return "\n".join(lines)


def _line_created(ev: Event, ctx: RenderContext) -> str:
    item = ctx.items[ev.entity_id]
    line = f"• {_item_ref(item)}"
    if item.assignee_ids:
        line += f" · {_e(ctx.users(item.assignee_ids))}"
    return line


def _one_assigned(ev: Event, ctx: RenderContext) -> str:
    item = ctx.items[ev.entity_id]
    return "\n".join(
        [
            f"👤 <b>{_e(ctx.user(ev.actor_id, 'Hệ thống'))}</b> đã giao việc cho "
            f"<b>{_e(ctx.users(_added_assignees(ev)))}</b>",
            f"<b>{_e(item.code)}</b> · {_e(_short(item.title))} · {_e(_status(item.status))}",
            _where(ctx, item.project_id, item.sprint_id, item.priority),
            f'<a href="{_e(item_link(item))}">Mở công việc</a>',
        ]
    )


def _line_assigned(ev: Event, ctx: RenderContext) -> str:
    return f"• {_item_ref(ctx.items[ev.entity_id])} → {_e(ctx.users(_added_assignees(ev)))}"


# ----------------------------------------------------------------------------- log công việc


def _one_work_log(ev: Event, ctx: RenderContext) -> str:
    log = ctx.work_logs[ev.entity_id]
    lines = [
        f"⏱ <b>{_e(ctx.user(log.user_id))}</b> đã ghi <b>{_hours(log.hours)}</b> · "
        f"{_e(ACTIVITY_LABEL.get(log.activity_type, log.activity_type))} · {_date(log.log_date)}"
        + ("" if log.is_billable else " · Không tính phí")
    ]
    if log.work_item_id and log.work_item_id in ctx.items:
        lines.append(f"🔧 {_item_ref(ctx.items[log.work_item_id], 90)}")
    elif log.requirement_id and log.requirement_id in ctx.requirements:
        lines.append(f"📥 {_req_ref(ctx.requirements[log.requirement_id], 90)}")
    if content := _plain(log.description):
        lines.append(f"📝 {_e(content)}")
    lines += [
        _where(ctx, log.project_id),
        f'<a href="{_e(_url(f"/projects/{log.project_id}/work-logs"))}">Mở log công việc</a>',
    ]
    return "\n".join(lines)


def _line_work_log(ev: Event, ctx: RenderContext) -> str:
    log = ctx.work_logs[ev.entity_id]
    line = f"• {_hours(log.hours)} · {_date(log.log_date)}"
    if log.work_item_id and log.work_item_id in ctx.items:
        line += f" · {_item_ref(ctx.items[log.work_item_id], 50)}"
    return line + f" — {_e(_plain(log.description, 80))}"


# ----------------------------------------------------------------------------- yêu cầu khách hàng


def _one_req_created(ev: Event, ctx: RenderContext) -> str:
    req = ctx.requirements[ev.entity_id]
    who = f"👤 {_e(ctx.user(ev.actor_id, 'Hệ thống'))} đã tạo · {_e(REQUIREMENT_TYPE_LABEL.get(req.type, req.type))}"
    if req.assignee_id:
        who += f" · Phụ trách: {_e(ctx.user(req.assignee_id))}"
    lines = [f"📥 Yêu cầu mới <b>{_e(req.code)}</b> · {_e(_short(req.title))}", who]
    if content := _plain(req.description):
        lines.append(f"📝 {_e(content)}")
    lines += [
        _where(ctx, req.project_id, priority=req.priority),
        f'<a href="{_e(requirement_link(req))}">Mở yêu cầu</a>',
    ]
    return "\n".join(lines)


def _line_req_created(ev: Event, ctx: RenderContext) -> str:
    return f"• {_req_ref(ctx.requirements[ev.entity_id])}"


def _one_req_status(ev: Event, ctx: RenderContext) -> str:
    req = ctx.requirements[ev.entity_id]
    who = f"👤 {_e(ctx.user(ev.actor_id, 'Hệ thống'))} đã chuyển"
    if req.assignee_id:
        who += f" · Phụ trách: {_e(ctx.user(req.assignee_id))}"
    lines = [
        f"🔄 Yêu cầu <b>{_e(req.code)}</b> · {_e(_short(req.title))}",
        f"{_e(_req_status(ev.old.get('status')))} → <b>{_e(_req_status(ev.new['status']))}</b>",
        who,
    ]
    if ev.new["status"] == RequirementStatus.rejected and req.rejected_reason:
        lines.append(f"❗ Lý do: {_e(_plain(req.rejected_reason))}")
    lines += [
        _where(ctx, req.project_id, priority=req.priority),
        f'<a href="{_e(requirement_link(req))}">Mở yêu cầu</a>',
    ]
    return "\n".join(lines)


def _line_req_status(ev: Event, ctx: RenderContext) -> str:
    req = ctx.requirements[ev.entity_id]
    return f"• {_req_ref(req)}: {_e(_req_status(ev.old.get('status')))} → <b>{_e(_req_status(ev.new['status']))}</b>"


def _one_comment(ev: Event, ctx: RenderContext) -> str:
    comment = ctx.comments[ev.entity_id]
    req = ctx.requirements[comment.requirement_id]
    head = f"💬 <b>{_e(ctx.user(comment.user_id))}</b> đã bình luận yêu cầu <b>{_e(req.code)}</b>"
    if comment.is_internal:
        head += " · 🔒 Nội bộ"
    return "\n".join(
        [
            head,
            _e(_short(req.title)),
            f"«{_e(_plain(comment.content))}»",
            _where(ctx, req.project_id),
            f'<a href="{_e(requirement_link(req))}">Mở yêu cầu</a>',
        ]
    )


def _line_comment(ev: Event, ctx: RenderContext) -> str:
    comment = ctx.comments[ev.entity_id]
    return f"• {_req_ref(ctx.requirements[comment.requirement_id], 40)}: «{_e(_plain(comment.content, 80))}»"


# ----------------------------------------------------------------------------- sprint


def _one_sprint(ev: Event, ctx: RenderContext) -> str:
    sprint = ctx.sprints[ev.entity_id]
    lines = [
        f"🏃 <b>{_e(ctx.user(ev.actor_id, 'Hệ thống'))}</b> đã {SPRINT_VERB.get(ev.new['status'], 'cập nhật')} "
        f"<b>{_e(sprint.name)}</b>",
        f"📅 {_date(sprint.start_date)} – {_date(sprint.end_date)}",
    ]
    if sprint.goal:
        lines.append(f"🎯 {_e(_plain(sprint.goal))}")
    page = "board" if ev.new["status"] == SprintStatus.active else "backlog"
    lines += [
        _where(ctx, sprint.project_id),
        f'<a href="{_e(_url(f"/projects/{sprint.project_id}/{page}"))}">Mở dự án</a>',
    ]
    return "\n".join(lines)


def _line_sprint(ev: Event, ctx: RenderContext) -> str:
    return f"• {_e(ctx.sprints[ev.entity_id].name)}: {SPRINT_VERB.get(ev.new['status'], 'cập nhật')}"


# ----------------------------------------------------------------------------- khai báo từng loại sự kiện


@dataclass(frozen=True)
class Spec:
    permission: str  # người nhận cá nhân phải còn quyền này trong dự án
    one: Callable[[Event, RenderContext], str]  # tin cho một sự kiện
    line: Callable[[Event, RenderContext], str]  # một dòng trong tin gộp
    many: str  # tiêu đề tin gộp: "{n}" = số sự kiện
    entity: Callable[[Event, RenderContext], Any]  # bản ghi gốc; None (đã xoá) -> không báo
    statuses: type | None = None  # lọc theo trạng thái mới (enum), None = không lọc
    # Người dùng coi là "của tôi" (scope mine); None = sự kiện không phân biệt phạm vi
    mine: Callable[[Event, RenderContext], list[int]] | None = None
    only: Callable[[Event, RenderContext], list[int]] | None = None  # chat cá nhân chỉ gửi cho những người này
    to_groups: Callable[[Event], bool] = lambda ev: True
    extra_permission: Callable[[Event, RenderContext], str | None] = lambda ev, ctx: None


def _live(entity: Any) -> Any:
    return entity if entity is not None and getattr(entity, "deleted_at", None) is None else None


def _item_people(item: WorkItem | None) -> list[int]:
    return [*item.assignee_ids, *([item.reporter_id] if item.reporter_id else [])] if item else []


def _req_people(req: Requirement | None) -> list[int]:
    return [uid for uid in (req.assignee_id, req.created_by) if uid] if req else []


def _comment_entity(ev: Event, ctx: RenderContext) -> RequirementComment | None:
    comment = _live(ctx.comments.get(ev.entity_id))
    return comment if comment and _live(ctx.requirements.get(comment.requirement_id)) else None


def _log_people(ev: Event, ctx: RenderContext) -> list[int]:
    log = ctx.work_logs[ev.entity_id]
    return _item_people(ctx.items.get(log.work_item_id or 0)) + _req_people(
        ctx.requirements.get(log.requirement_id or 0)
    )


def _comment_people(ev: Event, ctx: RenderContext) -> list[int]:
    req_id = ctx.comments[ev.entity_id].requirement_id
    return _req_people(ctx.requirements[req_id]) + list(ctx.commenters.get(req_id, ()))


SPECS: dict[NotificationEvent, Spec] = {
    E.work_item_status_changed: Spec(
        permission="work_item.view",
        one=_one_status,
        line=_line_status,
        many="đã chuyển trạng thái {n} công việc",
        entity=lambda ev, ctx: _live(ctx.items.get(ev.entity_id)),
        statuses=WorkItemStatus,
        mine=lambda ev, ctx: _item_people(ctx.items[ev.entity_id]),
    ),
    E.work_item_created: Spec(
        permission="work_item.view",
        one=_one_created,
        line=_line_created,
        many="đã tạo {n} công việc",
        entity=lambda ev, ctx: _live(ctx.items.get(ev.entity_id)),
    ),
    E.work_item_assigned: Spec(
        permission="work_item.view",
        one=_one_assigned,
        line=_line_assigned,
        many="đã giao {n} công việc",
        entity=lambda ev, ctx: _live(ctx.items.get(ev.entity_id)),
        only=lambda ev, ctx: _added_assignees(ev),
        # Công việc mới: group đã có tin "tạo công việc" (kèm người được giao)
        to_groups=lambda ev: bool(ev.old),
    ),
    E.work_log_created: Spec(
        permission="work_log.view",
        one=_one_work_log,
        line=_line_work_log,
        many="đã ghi {n} log công việc",
        entity=lambda ev, ctx: ctx.work_logs.get(ev.entity_id),
        mine=_log_people,
    ),
    E.requirement_created: Spec(
        permission="requirement.view",
        one=_one_req_created,
        line=_line_req_created,
        many="đã tạo {n} yêu cầu",
        entity=lambda ev, ctx: _live(ctx.requirements.get(ev.entity_id)),
        mine=lambda ev, ctx: _req_people(ctx.requirements[ev.entity_id]),
    ),
    E.requirement_status_changed: Spec(
        permission="requirement.view",
        one=_one_req_status,
        line=_line_req_status,
        many="đã chuyển trạng thái {n} yêu cầu",
        entity=lambda ev, ctx: _live(ctx.requirements.get(ev.entity_id)),
        statuses=RequirementStatus,
        mine=lambda ev, ctx: _req_people(ctx.requirements[ev.entity_id]),
    ),
    E.requirement_commented: Spec(
        permission="requirement.view",
        one=_one_comment,
        line=_line_comment,
        many="đã viết {n} bình luận",
        entity=_comment_entity,
        mine=_comment_people,
        extra_permission=lambda ev, ctx: (
            "requirement.view_internal" if ctx.comments[ev.entity_id].is_internal else None
        ),
    ),
    E.sprint_status_changed: Spec(
        permission="sprint.view",
        one=_one_sprint,
        line=_line_sprint,
        many="đã cập nhật {n} sprint",
        entity=lambda ev, ctx: ctx.sprints.get(ev.entity_id),
        statuses=SprintStatus,
    ),
}

# Đăng ký mặc định khi liên kết chat mới (cá nhân: scope mine)
DEFAULT_PERSONAL = [
    E.work_item_status_changed,
    E.work_item_assigned,
    E.work_log_created,
    E.requirement_status_changed,
    E.requirement_commented,
]
DEFAULT_GROUP = list(NotificationEvent)


def valid_statuses(event: NotificationEvent) -> set[str]:
    spec = SPECS[event].statuses
    return {s.value for s in spec} if spec else set()


# ----------------------------------------------------------------------------- người nhận

# Group của dự án nhận mọi thay đổi; chat cá nhân: không báo cho chính người vừa thao tác, phải còn quyền xem,
# scope 'mine' chỉ nhận việc / yêu cầu liên quan tới mình. `only`: chỉ gửi cho những người này (giao việc).
_RECIPIENTS = text("""
SELECT DISTINCT tc.id
  FROM notification_subscriptions s
  JOIN telegram_chats tc ON tc.id = s.telegram_chat_id AND tc.is_active
 WHERE s.enabled AND s.event = :event
   AND (CAST(:status AS text) IS NULL OR cardinality(s.statuses) = 0 OR CAST(:status AS text) = ANY (s.statuses))
   AND (
        (tc.project_id = :project_id AND :to_groups)
        OR (tc.user_id IS NOT NULL
            AND tc.user_id IS DISTINCT FROM CAST(:actor_id AS bigint)
            AND NOT tc.user_id = ANY (CAST(:skip AS bigint[]))
            AND (CAST(:only AS bigint[]) IS NULL OR tc.user_id = ANY (CAST(:only AS bigint[])))
            AND (CAST(:mine AS bigint[]) IS NULL OR s.scope = :scope_all OR tc.user_id = ANY (CAST(:mine AS bigint[])))
            AND fn_user_has_permission(tc.user_id, :permission, :project_id)
            AND (CAST(:extra AS text) IS NULL OR fn_user_has_permission(tc.user_id, :extra, :project_id)))
   )
""")


async def recipients(db: AsyncSession, ev: Event, ctx: RenderContext, skip: set[int] = frozenset()) -> list[int]:
    spec = SPECS[ev.kind]
    rows = await db.scalars(
        _RECIPIENTS,
        {
            "event": ev.kind.value,
            "status": ev.new.get("status") if spec.statuses else None,
            "project_id": ev.project_id,
            "to_groups": spec.to_groups(ev),
            "actor_id": ev.actor_id,
            "skip": list(skip),
            "only": spec.only(ev, ctx) if spec.only else None,
            "mine": spec.mine(ev, ctx) if spec.mine else None,
            "scope_all": NotificationScope.all.value,
            "permission": spec.permission,
            "extra": spec.extra_permission(ev, ctx),
        },
    )
    return list(rows)


def render(events: list[Event], ctx: RenderContext) -> str:
    """Một sự kiện: tin chi tiết. Nhiều sự kiện cùng loại trong một lần thao tác (vd: kết thúc sprint): tin gộp."""
    first = events[0]
    spec = SPECS[first.kind]
    if len(events) == 1:
        return spec.one(first, ctx)
    project = ctx.projects[first.project_id]
    actor = ctx.user(first.actor_id, "Hệ thống")
    lines = [f"🔔 <b>{_e(actor)}</b> {spec.many.format(n=len(events))} · 📁 {_e(project.key)}"]
    lines += [spec.line(ev, ctx) for ev in events[:MAX_LINES]]
    if len(events) > MAX_LINES:
        lines.append(f"… và {len(events) - MAX_LINES} mục khác")
    return "\n".join(lines)
