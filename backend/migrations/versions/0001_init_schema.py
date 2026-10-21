"""Schema ban đầu + dữ liệu gốc vai trò / quyền

Nội dung SQL nằm ở migrations/sql/ (hàm, trigger, view viết tay — không sinh được từ model).
Database tạo trước khi có Alembic (bằng init_db.sh cũ) đã có schema: bỏ qua, chỉ ghi nhận phiên bản.

Revision ID: 0001
Revises:
Create Date: 2026-10-21
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import context, op
from sqlalchemy import text
from sqlalchemy.util import await_only

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def run_sql_file(name: str) -> None:
    """Chạy file SQL nhiều câu lệnh (có $$ ... $$) qua kết nối asyncpg gốc, trong transaction của Alembic."""
    sql = (SQL_DIR / name).read_text()
    if context.is_offline_mode():
        op.execute(sql)
        return
    driver_conn = op.get_bind().connection.driver_connection
    await_only(driver_conn.execute(sql))


def upgrade() -> None:
    if op.get_bind().scalar(text("SELECT to_regclass('public.projects') IS NOT NULL")):
        return
    run_sql_file("0001_init_schema.sql")
    run_sql_file("0001_roles_permissions.sql")


def downgrade() -> None:
    raise NotImplementedError("Không hỗ trợ hạ về trước schema ban đầu")
