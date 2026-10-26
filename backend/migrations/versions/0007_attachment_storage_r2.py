"""File đính kèm chuyển từ MinIO sang Cloudflare R2

attachments.storage: 'cloudflare' (ảnh trên Cloudflare Images, storage_key = image id)
                   | 'r2' (file trên Cloudflare R2, storage_key = object key).
File gắn với công việc / yêu cầu (entity_type 'work_item' / 'requirement'), hoặc dán trong văn bản
(entity_type 'inline', file_name = '<mã 16 hex>/<tên file>', văn bản giữ dấu [File: <file_name>]).

Object key giữ nguyên: file đã có trên MinIO chỉ cần copy sang bucket R2 (vd `rclone copy minio:<bucket> r2:<bucket>`).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE attachments DROP CONSTRAINT IF EXISTS attachments_storage_check")
    op.execute("UPDATE attachments SET storage = 'r2' WHERE storage = 'minio'")
    op.execute(
        "ALTER TABLE attachments ADD CONSTRAINT attachments_storage_check CHECK (storage IN ('cloudflare', 'r2'))"
    )
    op.execute(
        "COMMENT ON COLUMN attachments.storage IS "
        "'cloudflare: ảnh trên Cloudflare Images; r2: file trên Cloudflare R2 (storage_key = object key)'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE attachments DROP CONSTRAINT attachments_storage_check")
    op.execute("UPDATE attachments SET storage = 'minio' WHERE storage = 'r2'")
    op.execute(
        "ALTER TABLE attachments ADD CONSTRAINT attachments_storage_check CHECK (storage IN ('cloudflare', 'minio'))"
    )
