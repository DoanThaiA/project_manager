"""Personal access token (PAT) và vai trò EXECUTIVE (ban lãnh đạo, chỉ đọc toàn bộ dự án)

PAT dùng cho client không đăng nhập bằng JWT (connector MCP). Chỉ lưu SHA-256 của token, không lưu token gốc.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Chỉ đọc: xem dự án, tiến độ, yêu cầu (kể cả bình luận nội bộ), công việc, giờ log, báo cáo, nhật ký, khách hàng
EXECUTIVE_PERMISSIONS = (
    "project.view",
    "sprint.view",
    "requirement.view",
    "requirement.view_internal",
    "work_item.view",
    "work_log.view",
    "report.view",
    "activity_log.view",
    "customer.view",
    "user.view",
)


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_api_tokens_user", "api_tokens", ["user_id"])

    op.execute(
        "INSERT INTO roles (code, name, scope, description, is_builtin) VALUES "
        "('EXECUTIVE', 'Ban lãnh đạo', 'system', 'Xem toàn bộ dự án, báo cáo, nhật ký; không sửa', true)"
    )
    codes = ", ".join(f"'{c}'" for c in EXECUTIVE_PERMISSIONS)
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        f"SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code IN ({codes}) "
        "WHERE r.code = 'EXECUTIVE' ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions WHERE role_id IN (SELECT id FROM roles WHERE code = 'EXECUTIVE')")
    op.execute("DELETE FROM user_roles WHERE role_id IN (SELECT id FROM roles WHERE code = 'EXECUTIVE')")
    op.execute("DELETE FROM roles WHERE code = 'EXECUTIVE'")
    op.drop_index("idx_api_tokens_user", table_name="api_tokens")
    op.drop_table("api_tokens")
