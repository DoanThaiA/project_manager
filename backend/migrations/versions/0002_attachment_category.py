"""Ảnh đính kèm công việc: phân loại ảnh lỗi / ảnh sau khi sửa

Ảnh lưu trên Cloudflare Images, attachments.storage_key là image id do Cloudflare sinh.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IF NOT EXISTS: an toàn với database đã chạy tay V2__attachment_category.sql trước khi có Alembic
    op.execute(
        "ALTER TABLE attachments ADD COLUMN IF NOT EXISTS category varchar(20) CHECK (category IN ('bug', 'result'))"
    )
    op.execute("COMMENT ON COLUMN attachments.category IS 'bug: ảnh chụp lỗi; result: ảnh kết quả sau khi sửa'")


def downgrade() -> None:
    op.drop_column("attachments", "category")
