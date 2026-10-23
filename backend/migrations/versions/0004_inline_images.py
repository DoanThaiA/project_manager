"""Ảnh dán trong ô văn bản (yêu cầu, bình luận, log công việc, sprint...)

attachments.entity_type thêm 'inline': ảnh gắn với dự án (entity_id = project_id), văn bản giữ dấu
[Ảnh: <tên file>] và tra URL theo tên file.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE attachments DROP CONSTRAINT IF EXISTS attachments_entity_type_check")
    op.execute(
        "ALTER TABLE attachments ADD CONSTRAINT attachments_entity_type_check "
        "CHECK (entity_type IN ('requirement', 'work_item', 'requirement_comment', 'sprint', 'inline'))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_attachments_inline_name ON attachments(project_id, file_name) "
        "WHERE entity_type = 'inline'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_attachments_inline_name")
    op.execute("DELETE FROM attachments WHERE entity_type = 'inline'")
    op.execute("ALTER TABLE attachments DROP CONSTRAINT attachments_entity_type_check")
    op.execute(
        "ALTER TABLE attachments ADD CONSTRAINT attachments_entity_type_check "
        "CHECK (entity_type IN ('requirement', 'work_item', 'requirement_comment', 'sprint'))"
    )
