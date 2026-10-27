"""Doanh nghiệp (companies) + mã nhân viên trên users — dùng chung với hệ thống LMS (lms_mcv)

- companies: doanh nghiệp, `code` là mã công ty nhập khi đăng nhập LMS (không phân biệt hoa thường,
  duy nhất giữa các công ty chưa xoá).
- users.company_id / users.employee_code: nhân viên thuộc doanh nghiệp. Đăng nhập LMS bằng
  mã công ty + mã nhân viên + mật khẩu (cùng password_hash với Project Manager).
  Mã nhân viên duy nhất trong một công ty (giữa các tài khoản chưa xoá); để NULL nếu tài khoản không dùng LMS.
- UNIQUE (company_id, id) trên users: để bảng LMS đặt FK kép, đảm bảo dữ liệu không gắn nhầm nhân viên công ty khác.

Tài khoản có sẵn không tự gán công ty: tạo công ty và gán mã nhân viên qua API / CLI của LMS.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-27
"""

from collections.abc import Sequence

from alembic import context, op
from sqlalchemy.util import await_only

revision: str = "0008"
down_revision: str | None = "0007"
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
CREATE TABLE companies (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code        citext       NOT NULL CHECK (code ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{1,29}$'),
    name        varchar(255) NOT NULL,
    short_name  varchar(100),
    tax_code    varchar(20),
    email       citext,
    phone       varchar(30),
    address     text,
    logo_url    varchar(500),
    status      varchar(10)  NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
    created_by  bigint REFERENCES users(id) ON DELETE SET NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    deleted_at  timestamptz
);
COMMENT ON TABLE companies IS 'Doanh nghiệp; code = mã công ty khi đăng nhập LMS';
CREATE UNIQUE INDEX uq_companies_code ON companies(code) WHERE deleted_at IS NULL;

CREATE TRIGGER trg_companies_updated_at BEFORE UPDATE ON companies
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
CREATE TRIGGER trg_companies_audit AFTER INSERT OR UPDATE OR DELETE ON companies
    FOR EACH ROW EXECUTE FUNCTION fn_audit_log();

ALTER TABLE users
    ADD COLUMN company_id    bigint REFERENCES companies(id) ON DELETE RESTRICT,
    ADD COLUMN employee_code citext CHECK (employee_code ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,29}$'),
    -- Có mã nhân viên thì phải thuộc một công ty
    ADD CONSTRAINT ck_users_employee_company CHECK (employee_code IS NULL OR company_id IS NOT NULL),
    ADD CONSTRAINT uq_users_company_id UNIQUE (company_id, id);
COMMENT ON COLUMN users.company_id IS 'Doanh nghiệp của nhân viên (LMS)';
COMMENT ON COLUMN users.employee_code IS
    'Mã nhân viên, duy nhất trong công ty; đăng nhập LMS bằng mã công ty + mã nhân viên';
CREATE UNIQUE INDEX uq_users_company_employee ON users(company_id, employee_code)
    WHERE employee_code IS NOT NULL AND deleted_at IS NULL;
""")


def downgrade() -> None:
    run_sql("""
DROP INDEX IF EXISTS uq_users_company_employee;
ALTER TABLE users
    DROP CONSTRAINT uq_users_company_id,
    DROP CONSTRAINT ck_users_employee_company,
    DROP COLUMN employee_code,
    DROP COLUMN company_id;
DROP TABLE companies;
""")
