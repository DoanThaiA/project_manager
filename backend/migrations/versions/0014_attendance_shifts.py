"""Ca làm việc cho chấm công: lịch theo từng ngày trong tuần, gán theo user, tính công

- attendance_shifts: ca làm (tên, số phút cho phép muộn / về sớm, ca mặc định).
- attendance_shift_days: lịch của ca theo từng thứ (giờ vào / về, nghỉ trưa, số công của ngày). Có dòng = ngày
  làm việc, không có dòng = ngày nghỉ. Có sẵn 2 ca:
    "Hành chính" (mặc định): T2 - T6 08:00 - 17:30, nghỉ 12:00 - 13:30, 1 công; T7 08:00 - 12:00, 0,5 công.
    "Ca sáng": T2 - T6 08:00 - 12:00, 1 công; nghỉ T7.
  Thay cho ca cố định trong config (attendance_* của 0013).
- users.attendance_shift_id: ca của user; NULL = ca mặc định.
- attendance_records.shift_id: ca áp dụng lúc chấm (giữ nguyên khi user đổi ca sau này); credit: số công của
  bản ghi (có đủ giờ vào + giờ về trong ngày làm việc của ca thì được công của ngày đó). Bản ghi cũ gán ca mặc định.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-03
"""

from collections.abc import Sequence

from alembic import context, op
from sqlalchemy.util import await_only

revision: str = "0014"
down_revision: str | None = "0013"
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
CREATE TABLE attendance_shifts (
    id                   int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                 varchar(100) NOT NULL,
    late_grace_minutes   smallint NOT NULL DEFAULT 5,
    early_grace_minutes  smallint NOT NULL DEFAULT 0,
    is_default           boolean  NOT NULL DEFAULT false,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_attendance_shifts_name UNIQUE (name),
    CONSTRAINT ck_attendance_shifts_grace CHECK (
        late_grace_minutes BETWEEN 0 AND 240 AND early_grace_minutes BETWEEN 0 AND 240
    )
);
COMMENT ON TABLE attendance_shifts IS 'Ca làm việc cho chấm công; is_default = ca của user chưa được gán ca';
CREATE UNIQUE INDEX uq_attendance_shifts_default ON attendance_shifts(is_default) WHERE is_default;

CREATE TRIGGER trg_attendance_shifts_updated_at BEFORE UPDATE ON attendance_shifts
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
CREATE TRIGGER trg_attendance_shifts_audit AFTER INSERT OR UPDATE OR DELETE ON attendance_shifts
    FOR EACH ROW EXECUTE FUNCTION fn_audit_log();

CREATE TABLE attendance_shift_days (
    shift_id     int      NOT NULL REFERENCES attendance_shifts(id) ON DELETE CASCADE,
    weekday      smallint NOT NULL,
    start_time   time     NOT NULL,
    end_time     time     NOT NULL,
    break_start  time,
    break_end    time,
    credit       numeric(3,2) NOT NULL DEFAULT 1,
    PRIMARY KEY (shift_id, weekday),
    CONSTRAINT ck_attendance_shift_days_weekday CHECK (weekday BETWEEN 1 AND 7),
    CONSTRAINT ck_attendance_shift_days_time CHECK (start_time < end_time),
    CONSTRAINT ck_attendance_shift_days_break CHECK (
        (break_start IS NULL AND break_end IS NULL)
        OR (break_start < break_end AND break_start >= start_time AND break_end <= end_time)
    ),
    CONSTRAINT ck_attendance_shift_days_credit CHECK (credit > 0 AND credit <= 1)
);
COMMENT ON TABLE attendance_shift_days IS 'Lịch của ca theo thứ; không có dòng = ngày nghỉ của ca';
COMMENT ON COLUMN attendance_shift_days.weekday IS 'ISO: 1 = thứ 2 ... 7 = chủ nhật';
COMMENT ON COLUMN attendance_shift_days.credit IS 'Số công của ngày (vd T7 làm buổi sáng = 0,5)';

WITH s AS (
    INSERT INTO attendance_shifts (name, is_default) VALUES ('Hành chính', true), ('Ca sáng', false)
    RETURNING id, name
)
INSERT INTO attendance_shift_days (shift_id, weekday, start_time, end_time, break_start, break_end, credit)
SELECT s.id, d.weekday, d.start_time, d.end_time, d.break_start, d.break_end, d.credit
  FROM s
  JOIN (VALUES
    ('Hành chính', 1, time '08:00', time '17:30', time '12:00', time '13:30', 1.0),
    ('Hành chính', 2, time '08:00', time '17:30', time '12:00', time '13:30', 1.0),
    ('Hành chính', 3, time '08:00', time '17:30', time '12:00', time '13:30', 1.0),
    ('Hành chính', 4, time '08:00', time '17:30', time '12:00', time '13:30', 1.0),
    ('Hành chính', 5, time '08:00', time '17:30', time '12:00', time '13:30', 1.0),
    ('Hành chính', 6, time '08:00', time '12:00', NULL,          NULL,          0.5),
    ('Ca sáng',    1, time '08:00', time '12:00', NULL,          NULL,          1.0),
    ('Ca sáng',    2, time '08:00', time '12:00', NULL,          NULL,          1.0),
    ('Ca sáng',    3, time '08:00', time '12:00', NULL,          NULL,          1.0),
    ('Ca sáng',    4, time '08:00', time '12:00', NULL,          NULL,          1.0),
    ('Ca sáng',    5, time '08:00', time '12:00', NULL,          NULL,          1.0)
  ) AS d(shift_name, weekday, start_time, end_time, break_start, break_end, credit) ON d.shift_name = s.name;

ALTER TABLE users ADD COLUMN attendance_shift_id int REFERENCES attendance_shifts(id) ON DELETE SET NULL;
COMMENT ON COLUMN users.attendance_shift_id IS 'Ca chấm công của user; NULL = ca mặc định';

ALTER TABLE attendance_records
    ADD COLUMN shift_id int REFERENCES attendance_shifts(id) ON DELETE RESTRICT,
    ADD COLUMN credit numeric(3,2) NOT NULL DEFAULT 0 CHECK (credit >= 0);
COMMENT ON COLUMN attendance_records.shift_id IS 'Ca áp dụng lúc chấm (không đổi khi user đổi ca sau này)';
COMMENT ON COLUMN attendance_records.credit IS 'Số công: công của ngày nếu có đủ giờ vào + giờ về, ngược lại 0';
-- Bản ghi tạo từ 0013: ca mặc định; có giờ về trong ngày làm việc thì được công của ngày đó
UPDATE attendance_records SET shift_id = (SELECT id FROM attendance_shifts WHERE is_default);
UPDATE attendance_records r
   SET credit = d.credit
  FROM attendance_shift_days d
 WHERE d.shift_id = r.shift_id AND d.weekday = extract(isodow FROM r.work_date) AND r.check_out_at IS NOT NULL;
ALTER TABLE attendance_records ALTER COLUMN shift_id SET NOT NULL;
""")


def downgrade() -> None:
    run_sql("""
ALTER TABLE attendance_records DROP COLUMN credit, DROP COLUMN shift_id;
ALTER TABLE users DROP COLUMN attendance_shift_id;
DROP TABLE attendance_shift_days;
DROP TABLE attendance_shifts;
""")
