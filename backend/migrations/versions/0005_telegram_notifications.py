"""Thông báo Telegram (cá nhân / group) khi có thay đổi — trước mắt: đổi trạng thái công việc

- telegram_chats: chat đã liên kết với bot — chat riêng của một người dùng, hoặc group gắn với một dự án
- telegram_link_codes: mã liên kết dùng một lần (deep link t.me/<bot>?start=<mã> / ?startgroup=<mã>)
- notification_subscriptions: chat nào nhận sự kiện nào (lọc theo trạng thái, phạm vi)
- notification_events: hàng đợi, trigger trên activity_logs điền vào; worker lấy bằng FOR UPDATE SKIP LOCKED
  nên không sót bản ghi của transaction commit muộn, chạy nhiều instance cũng không trùng
- notification_deliveries: tin cần gửi tới từng chat (retry riêng từng tin)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-23
"""

from collections.abc import Sequence

from alembic import context, op
from sqlalchemy.util import await_only

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def run_sql(sql: str) -> None:
    """Nhiều câu lệnh (có $$ ... $$) -> chạy qua kết nối asyncpg gốc, như 0001."""
    if context.is_offline_mode():
        op.execute(sql)
        return
    await_only(op.get_bind().connection.driver_connection.execute(sql))


def upgrade() -> None:
    run_sql("""
CREATE TABLE telegram_chats (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chat_id     bigint NOT NULL,
    type        varchar(20) NOT NULL CHECK (type IN ('private', 'group', 'supergroup', 'channel')),
    title       varchar(255),
    user_id     bigint REFERENCES users(id) ON DELETE CASCADE,
    project_id  bigint REFERENCES projects(id) ON DELETE CASCADE,
    is_active   boolean NOT NULL DEFAULT true,
    linked_by   bigint REFERENCES users(id) ON DELETE SET NULL,
    linked_at   timestamptz NOT NULL DEFAULT now(),
    -- Chat riêng thuộc một người dùng, hoặc group thuộc một dự án
    CHECK ((user_id IS NULL) <> (project_id IS NULL))
);
COMMENT ON TABLE telegram_chats IS 'Chat Telegram đã liên kết: chat riêng của người dùng hoặc group của dự án';
CREATE UNIQUE INDEX uq_telegram_chats_user ON telegram_chats(user_id) WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX uq_telegram_chats_private ON telegram_chats(chat_id) WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX uq_telegram_chats_project ON telegram_chats(project_id, chat_id) WHERE project_id IS NOT NULL;
CREATE INDEX idx_telegram_chats_chat ON telegram_chats(chat_id);

CREATE TABLE telegram_link_codes (
    code        varchar(64) PRIMARY KEY,
    kind        varchar(10) NOT NULL CHECK (kind IN ('user', 'project')),
    user_id     bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id  bigint REFERENCES projects(id) ON DELETE CASCADE,
    expires_at  timestamptz NOT NULL,
    used_at     timestamptz,
    CHECK (kind = 'user' OR project_id IS NOT NULL)
);
COMMENT ON TABLE telegram_link_codes IS 'Mã liên kết chat Telegram dùng một lần; user_id: người tạo mã';

CREATE TABLE notification_subscriptions (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    telegram_chat_id  bigint NOT NULL REFERENCES telegram_chats(id) ON DELETE CASCADE,
    event             varchar(50) NOT NULL,
    scope             varchar(20) NOT NULL DEFAULT 'all' CHECK (scope IN ('all', 'mine')),
    statuses          text[] NOT NULL DEFAULT '{}',
    enabled           boolean NOT NULL DEFAULT true,
    UNIQUE (telegram_chat_id, event)
);
COMMENT ON COLUMN notification_subscriptions.scope IS
    'Chat cá nhân: all = mọi công việc trong các dự án mình tham gia, mine = việc giao cho mình / mình tạo';
COMMENT ON COLUMN notification_subscriptions.statuses IS
    'Chỉ báo khi chuyển sang các trạng thái này; rỗng = mọi trạng thái';

CREATE TABLE notification_events (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    activity_log_id  bigint NOT NULL
);

CREATE TABLE notification_deliveries (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    telegram_chat_id  bigint NOT NULL REFERENCES telegram_chats(id) ON DELETE CASCADE,
    event             varchar(50) NOT NULL,
    text              text NOT NULL,
    status            varchar(10) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed')),
    attempts          smallint NOT NULL DEFAULT 0,
    next_try_at       timestamptz NOT NULL DEFAULT now(),
    error             text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    sent_at           timestamptz
);
CREATE INDEX idx_notification_deliveries_due ON notification_deliveries(next_try_at) WHERE status = 'pending';

-- Đưa thay đổi cần báo vào hàng đợi; chưa ai đăng ký thì bỏ qua để bảng không phình khi tắt tính năng
CREATE FUNCTION fn_notification_enqueue() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.entity_type IN ('work_items', 'requirements', 'work_logs')
       AND EXISTS (SELECT 1 FROM notification_subscriptions WHERE enabled) THEN
        INSERT INTO notification_events (activity_log_id) VALUES (NEW.id);
    END IF;
    RETURN NULL;
END $$;

CREATE TRIGGER trg_activity_logs_notify
    AFTER INSERT ON activity_logs
    FOR EACH ROW EXECUTE FUNCTION fn_notification_enqueue();

INSERT INTO permissions (code, module, name)
VALUES ('project.notification.manage', 'project', 'Cấu hình thông báo Telegram của dự án');
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p
 WHERE r.code IN ('PRODUCT_OWNER', 'SCRUM_MASTER') AND p.code = 'project.notification.manage';
""")


def downgrade() -> None:
    run_sql("""
DELETE FROM permissions WHERE code = 'project.notification.manage';
DROP TRIGGER IF EXISTS trg_activity_logs_notify ON activity_logs;
DROP FUNCTION IF EXISTS fn_notification_enqueue();
DROP TABLE IF EXISTS notification_deliveries, notification_events, notification_subscriptions,
                     telegram_link_codes, telegram_chats;
""")
