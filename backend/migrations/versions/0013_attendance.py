"""Chấm công theo IP mạng công ty (docs/ATTENDANCE.md)

- attendance_networks: IP / dải IP công cộng của văn phòng. Check-in / check-out chỉ được chấp nhận khi IP
  của request nằm trong một mạng đang bật (`cidr >>= ip`).
- attendance_records: bảng công, mỗi user một dòng mỗi ngày (giờ vào, giờ về, IP, số phút muộn / về sớm).
  Ca làm cố định trong config (attendance_*), không có bảng ca. Không lưu trạng thái: suy ra khi đọc.
- attendance_events: log thô mọi lần bấm, kể cả bị từ chối (ngoài mạng, dùng token PAT...). Không audit.
- Quyền hệ thống attendance.checkin / attendance.view / attendance.manage + vai trò HR (Nhân sự).

Audit: attendance_networks ghi activity_logs mọi thay đổi; attendance_records chỉ ghi khi admin sửa / thêm
(source = 'admin') hoặc xoá — check-in hằng ngày đã có trong attendance_events.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-02
"""

from collections.abc import Sequence

from alembic import context, op
from sqlalchemy.util import await_only

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def run_sql(sql: str) -> None:
    """Nhiều câu lệnh -> chạy qua kết nối asyncpg gốc, như 0001."""
    if context.is_offline_mode():
        op.execute(sql)
        return
    await_only(op.get_bind().connection.driver_connection.execute(sql))


def upgrade() -> None:
    run_sql("""
CREATE TABLE attendance_networks (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        varchar(100) NOT NULL,
    cidr        cidr         NOT NULL,
    is_active   boolean      NOT NULL DEFAULT true,
    note        text,
    created_by  bigint REFERENCES users(id) ON DELETE SET NULL,
    created_at  timestamptz  NOT NULL DEFAULT now(),
    updated_at  timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT uq_attendance_networks_cidr UNIQUE (cidr)
);
COMMENT ON TABLE attendance_networks IS 'IP công cộng của văn phòng, được phép chấm công';
CREATE INDEX idx_attendance_networks_cidr ON attendance_networks USING gist (cidr inet_ops) WHERE is_active;

CREATE TRIGGER trg_attendance_networks_updated_at BEFORE UPDATE ON attendance_networks
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
CREATE TRIGGER trg_attendance_networks_audit AFTER INSERT OR UPDATE OR DELETE ON attendance_networks
    FOR EACH ROW EXECUTE FUNCTION fn_audit_log();

CREATE TABLE attendance_records (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id              bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    work_date            date   NOT NULL,
    check_in_at          timestamptz NOT NULL,
    check_in_ip          inet,
    check_in_network_id  bigint REFERENCES attendance_networks(id) ON DELETE SET NULL,
    check_out_at         timestamptz,
    check_out_ip         inet,
    check_out_network_id bigint REFERENCES attendance_networks(id) ON DELETE SET NULL,
    late_minutes         int NOT NULL DEFAULT 0 CHECK (late_minutes >= 0),
    early_leave_minutes  int NOT NULL DEFAULT 0 CHECK (early_leave_minutes >= 0),
    worked_minutes       int CHECK (worked_minutes >= 0),
    source               varchar(10) NOT NULL DEFAULT 'web',
    note                 text,
    adjusted_by          bigint REFERENCES users(id) ON DELETE SET NULL,
    adjusted_reason      text,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_attendance_records_user_date UNIQUE (user_id, work_date),
    CONSTRAINT ck_attendance_records_source CHECK (source IN ('web', 'admin')),
    CONSTRAINT ck_attendance_records_out_after_in CHECK (check_out_at IS NULL OR check_out_at >= check_in_at),
    CONSTRAINT ck_attendance_records_admin_reason CHECK (source = 'web' OR adjusted_reason IS NOT NULL)
);
COMMENT ON TABLE attendance_records IS 'Bảng công: mỗi user một dòng mỗi ngày (giờ Việt Nam)';
COMMENT ON COLUMN attendance_records.late_minutes IS 'Số phút vào sau giờ bắt đầu ca';
COMMENT ON COLUMN attendance_records.early_leave_minutes IS 'Số phút về trước giờ kết thúc ca';
COMMENT ON COLUMN attendance_records.worked_minutes IS 'Giờ ra - giờ vào, trừ phần trùng nghỉ trưa';
COMMENT ON COLUMN attendance_records.source IS 'web = nhân viên tự chấm | admin = quản lý thêm / sửa';
CREATE INDEX idx_attendance_records_date ON attendance_records(work_date);

CREATE TRIGGER trg_attendance_records_updated_at BEFORE UPDATE ON attendance_records
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
CREATE TRIGGER trg_attendance_records_audit AFTER INSERT OR UPDATE ON attendance_records
    FOR EACH ROW WHEN (NEW.source = 'admin') EXECUTE FUNCTION fn_audit_log();
CREATE TRIGGER trg_attendance_records_audit_delete AFTER DELETE ON attendance_records
    FOR EACH ROW EXECUTE FUNCTION fn_audit_log();

CREATE TABLE attendance_events (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     bigint      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    action      varchar(10) NOT NULL,
    accepted    boolean     NOT NULL,
    reason      varchar(30),
    ip          inet,
    network_id  bigint REFERENCES attendance_networks(id) ON DELETE SET NULL,
    user_agent  text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_attendance_events_action CHECK (action IN ('check_in', 'check_out'))
);
COMMENT ON TABLE attendance_events IS 'Log mọi lần bấm chấm công, kể cả bị từ chối';
COMMENT ON COLUMN attendance_events.reason IS 'outside_network | not_checked_in | api_token';
CREATE INDEX idx_attendance_events_user ON attendance_events(user_id, created_at DESC);
CREATE INDEX idx_attendance_events_rejected ON attendance_events(created_at DESC) WHERE NOT accepted;

INSERT INTO permissions (code, module, name) VALUES
    ('attendance.checkin', 'attendance', 'Chấm công (check-in / check-out)'),
    ('attendance.view',    'attendance', 'Xem bảng công của mọi người'),
    ('attendance.manage',  'attendance', 'Cấu hình mạng công ty, sửa công');
INSERT INTO roles (code, name, scope, is_builtin, description) VALUES
    ('HR', 'Nhân sự', 'system', true, 'Quản lý chấm công');
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
  FROM (VALUES
    ('SYSTEM_ADMIN', 'attendance.checkin'), ('SYSTEM_ADMIN', 'attendance.view'), ('SYSTEM_ADMIN', 'attendance.manage'),
    ('HR', 'attendance.checkin'), ('HR', 'attendance.view'), ('HR', 'attendance.manage'), ('HR', 'user.view'),
    ('PROJECT_MANAGER', 'attendance.checkin'),
    ('STAFF', 'attendance.checkin'),
    ('EXECUTIVE', 'attendance.view')
  ) AS m(role_code, perm_code)
  JOIN roles r       ON r.code = m.role_code
  JOIN permissions p ON p.code = m.perm_code
ON CONFLICT DO NOTHING;
""")


def downgrade() -> None:
    run_sql("""
DELETE FROM user_roles WHERE role_id IN (SELECT id FROM roles WHERE code = 'HR');
DELETE FROM roles WHERE code = 'HR';
DELETE FROM permissions WHERE module = 'attendance';
DROP TABLE attendance_events;
DROP TABLE attendance_records;
DROP TABLE attendance_networks;
""")
