"""File đính kèm (tài liệu, PDF, Excel, zip...) của công việc và yêu cầu lưu trên MinIO

attachments.storage: 'cloudflare' (ảnh, storage_key = image id Cloudflare) | 'minio' (file, storage_key = object key).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE attachments ADD COLUMN storage varchar(20) NOT NULL DEFAULT 'cloudflare' "
        "CHECK (storage IN ('cloudflare', 'minio'))"
    )
    op.execute(
        "COMMENT ON COLUMN attachments.storage IS "
        "'cloudflare: ảnh trên Cloudflare Images; minio: file trên MinIO (storage_key = object key)'"
    )


def downgrade() -> None:
    op.execute("DELETE FROM attachments WHERE storage = 'minio'")
    op.drop_column("attachments", "storage")
