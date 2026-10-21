"""Cho phép dùng lại mã dự án đã xoá

Mã dự án chỉ duy nhất giữa các dự án chưa xoá (partial unique index). Mã yêu cầu / công việc
(<KEY>-REQ-0001, <KEY>-12) đổi từ duy nhất toàn hệ thống sang duy nhất trong dự án — nếu không,
dự án mới dùng lại mã ERP sẽ sinh ERP-1 trùng với ERP-1 của dự án đã xoá.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("projects_key_key", "projects", type_="unique")
    op.create_index("uq_projects_key_active", "projects", ["key"], unique=True, postgresql_where="deleted_at IS NULL")

    for table in ("requirements", "work_items"):
        op.drop_constraint(f"{table}_code_key", table, type_="unique")
        op.create_unique_constraint(f"{table}_project_id_code_key", table, ["project_id", "code"])


def downgrade() -> None:
    # Lỗi nếu đã có dự án / mã công việc trùng với dữ liệu của dự án đã xoá
    for table in ("requirements", "work_items"):
        op.drop_constraint(f"{table}_project_id_code_key", table, type_="unique")
        op.create_unique_constraint(f"{table}_code_key", table, ["code"])

    op.drop_index("uq_projects_key_active", "projects")
    op.create_unique_constraint("projects_key_key", "projects", ["key"])
