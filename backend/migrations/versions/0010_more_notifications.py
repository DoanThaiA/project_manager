"""Thông báo Telegram cho các thay đổi khác ngoài đổi trạng thái công việc

Sự kiện mới: tạo công việc, giao việc, log công việc mới, yêu cầu mới / đổi trạng thái, bình luận yêu cầu,
sprint bắt đầu / kết thúc. Hàng đợi nhận thêm activity_logs của sprints và requirement_comments.

Chat đã liên kết được bật sẵn các thông báo mặc định (như khi liên kết mới — xem events.DEFAULT_*):
group nhận tất cả; chat cá nhân nhận giao việc, log công việc, đổi trạng thái yêu cầu, bình luận (phạm vi
"của tôi"). Người dùng tắt / đổi trong trang Thông báo.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-27
"""

from collections.abc import Sequence

from alembic import context, op
from sqlalchemy.util import await_only

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_EVENTS = (
    "work_item.created",
    "work_item.assigned",
    "work_log.created",
    "requirement.created",
    "requirement.status_changed",
    "requirement.commented",
    "sprint.status_changed",
)
PERSONAL_EVENTS = ("work_item.assigned", "work_log.created", "requirement.status_changed", "requirement.commented")


def run_sql(sql: str) -> None:
    """Nhiều câu lệnh (có $$ ... $$) -> chạy qua kết nối asyncpg gốc, như 0001."""
    if context.is_offline_mode():
        op.execute(sql)
        return
    await_only(op.get_bind().connection.driver_connection.execute(sql))


def _enqueue_function(entity_types: str) -> str:
    return f"""
CREATE OR REPLACE FUNCTION fn_notification_enqueue() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.entity_type IN ({entity_types})
       AND EXISTS (SELECT 1 FROM notification_subscriptions WHERE enabled) THEN
        INSERT INTO notification_events (activity_log_id) VALUES (NEW.id);
    END IF;
    RETURN NULL;
END $$;
"""


def _values(events: tuple[str, ...]) -> str:
    return ", ".join(f"('{e}')" for e in events)


def upgrade() -> None:
    run_sql(
        _enqueue_function("'work_items', 'requirements', 'requirement_comments', 'work_logs', 'sprints'")
        + f"""
INSERT INTO notification_subscriptions (telegram_chat_id, event, scope)
SELECT tc.id, e.event, 'all'
  FROM telegram_chats tc CROSS JOIN (VALUES {_values(NEW_EVENTS)}) AS e(event)
 WHERE tc.project_id IS NOT NULL
ON CONFLICT (telegram_chat_id, event) DO NOTHING;

INSERT INTO notification_subscriptions (telegram_chat_id, event, scope)
SELECT tc.id, e.event, 'mine'
  FROM telegram_chats tc CROSS JOIN (VALUES {_values(PERSONAL_EVENTS)}) AS e(event)
 WHERE tc.user_id IS NOT NULL
ON CONFLICT (telegram_chat_id, event) DO NOTHING;
"""
    )


def downgrade() -> None:
    events = ", ".join(f"'{e}'" for e in NEW_EVENTS)
    run_sql(
        _enqueue_function("'work_items', 'requirements', 'work_logs'")
        + f"DELETE FROM notification_subscriptions WHERE event IN ({events});"
    )
