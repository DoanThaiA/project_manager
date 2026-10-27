"""Công việc giao cho nhiều người: work_items.assignee_id -> assignee_ids bigint[]

Dữ liệu cũ: assignee_id có giá trị -> assignee_ids = {assignee_id}. Mảng không đặt được FK nên API kiểm tra
từng người là thành viên dự án; lọc theo người phụ trách dùng `assignee_ids @> ARRAY[id]` (GIN index).
Nhật ký (fn_audit_log) tự ghi thay đổi cột assignee_ids như các cột khác.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE work_items ADD COLUMN assignee_ids bigint[] NOT NULL DEFAULT '{}'")
    op.execute("UPDATE work_items SET assignee_ids = ARRAY[assignee_id] WHERE assignee_id IS NOT NULL")
    op.execute("DROP INDEX IF EXISTS idx_work_items_assignee")
    op.execute("ALTER TABLE work_items DROP COLUMN assignee_id")
    op.execute(
        "CREATE INDEX idx_work_items_assignees ON work_items USING gin (assignee_ids) WHERE deleted_at IS NULL"
    )
    op.execute("COMMENT ON COLUMN work_items.assignee_ids IS 'Người phụ trách (nhiều người), id users'")


def downgrade() -> None:
    # Quay lại một người: giữ người đầu tiên
    op.execute("DROP INDEX IF EXISTS idx_work_items_assignees")
    op.execute("ALTER TABLE work_items ADD COLUMN assignee_id bigint REFERENCES users(id) ON DELETE SET NULL")
    op.execute(
        "UPDATE work_items w SET assignee_id = w.assignee_ids[1] "
        "WHERE cardinality(w.assignee_ids) > 0 AND EXISTS (SELECT 1 FROM users u WHERE u.id = w.assignee_ids[1])"
    )
    op.execute("ALTER TABLE work_items DROP COLUMN assignee_ids")
    op.execute(
        "CREATE INDEX idx_work_items_assignee ON work_items(assignee_id, status) WHERE deleted_at IS NULL"
    )
