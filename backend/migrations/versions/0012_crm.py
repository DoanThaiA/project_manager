"""CRM theo dự án: khách liên hệ qua Gmail (n8n lọc email, AI trích xuất thông tin)

- crm_contacts: khách liên hệ của một dự án (KHÔNG phải users / customers của hệ thống). Duy nhất theo
  (project_id, email): mọi email cùng người gửi gộp vào một khách. Có trạng thái theo dõi
  (mới -> đã liên hệ -> đã báo giá -> đang thương lượng -> chốt / không thành / spam), người phụ trách, ghi chú.
- crm_email_leads: mỗi email khách hỏi mua / báo giá / hỏi thông tin = 1 dòng (theo kpacking_email_leads).
  email_message_id duy nhất trong dự án: n8n gửi lại cùng email thì bỏ qua. Thông tin khách AI trích xuất
  được giữ nguyên theo từng email; crm_contacts chỉ lấy các trường còn trống.
- Quyền crm.view / crm.create / crm.update / crm.delete. n8n gọi POST /projects/{pid}/crm/emails/ingest bằng
  token truy cập (PAT) của tài khoản có quyền crm.create trong dự án.

Audit: crm_contacts ghi activity_logs (đổi trạng thái, phụ trách...). crm_email_leads không audit để không
chép nội dung email vào nhật ký.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-31
"""

from collections.abc import Sequence

from alembic import context, op
from sqlalchemy.util import await_only

revision: str = "0012"
down_revision: str | None = "0011"
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
CREATE TABLE crm_contacts (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id    bigint       NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    email         citext       NOT NULL,
    full_name     varchar(255),
    contact_email citext,
    phone         varchar(50),
    company       varchar(255),
    address       text,
    status        varchar(20)  NOT NULL DEFAULT 'new',
    assignee_id   bigint REFERENCES users(id) ON DELETE SET NULL,
    note          text,
    source        varchar(30)  NOT NULL DEFAULT 'gmail',
    created_by    bigint REFERENCES users(id) ON DELETE SET NULL,
    created_at    timestamptz  NOT NULL DEFAULT now(),
    updated_at    timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT uq_crm_contacts_project_email UNIQUE (project_id, email),
    CONSTRAINT ck_crm_contacts_status
        CHECK (status IN ('new', 'contacted', 'quoted', 'negotiating', 'won', 'lost', 'spam'))
);
COMMENT ON TABLE  crm_contacts IS 'Khách liên hệ của dự án (từ Gmail qua n8n, hoặc nhập tay); không phải users';
COMMENT ON COLUMN crm_contacts.email IS 'Email người gửi (header Gmail) - khoá gộp các email của cùng khách';
COMMENT ON COLUMN crm_contacts.contact_email IS 'Email liên hệ khác khách ghi trong nội dung';
COMMENT ON COLUMN crm_contacts.status IS
    'new | contacted = đã liên hệ | quoted = đã báo giá | negotiating = đang thương lượng | won | lost | spam';
CREATE INDEX idx_crm_contacts_project_status ON crm_contacts(project_id, status);
CREATE INDEX idx_crm_contacts_assignee ON crm_contacts(assignee_id) WHERE assignee_id IS NOT NULL;

CREATE TRIGGER trg_crm_contacts_updated_at BEFORE UPDATE ON crm_contacts
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
CREATE TRIGGER trg_crm_contacts_audit AFTER INSERT OR UPDATE OR DELETE ON crm_contacts
    FOR EACH ROW EXECUTE FUNCTION fn_audit_log();

CREATE TABLE crm_email_leads (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id       bigint        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    contact_id       bigint        NOT NULL REFERENCES crm_contacts(id) ON DELETE CASCADE,

    -- Thông tin email (lấy trực tiếp từ Gmail)
    email_message_id varchar(100)  NOT NULL,
    email_thread_id  varchar(100),
    received_at      timestamptz   NOT NULL,
    subject          varchar(998),
    content          text,

    -- Thông tin khách (AI trích xuất, riêng email lấy từ header Gmail)
    customer_name    varchar(255),
    customer_email   citext        NOT NULL,
    contact_email    citext,
    phone            varchar(50),
    company          varchar(255),
    address          text,

    -- Nhu cầu (AI trích xuất, giữ nguyên văn khách viết)
    inquiry_type     varchar(20)   NOT NULL DEFAULT 'khac',
    product_type     varchar(255),
    quantity         varchar(255),
    specifications   text,
    budget           varchar(255),
    deadline         varchar(255),
    summary          text,
    ai_confidence    numeric(3,2),

    source           varchar(30)   NOT NULL DEFAULT 'gmail',
    created_at       timestamptz   NOT NULL DEFAULT now(),

    CONSTRAINT uq_crm_email_leads_message UNIQUE (project_id, email_message_id),
    CONSTRAINT ck_crm_email_leads_inquiry_type
        CHECK (inquiry_type IN ('dat_hang', 'bao_gia', 'hoi_thong_tin', 'khac')),
    CONSTRAINT ck_crm_email_leads_ai_confidence CHECK (ai_confidence BETWEEN 0 AND 1)
);
COMMENT ON TABLE  crm_email_leads IS 'Email khách liên hệ (n8n lọc từ Gmail, AI trích xuất nhu cầu)';
COMMENT ON COLUMN crm_email_leads.email_message_id IS 'Mã email Gmail - khoá chống trùng khi n8n gửi lại';
COMMENT ON COLUMN crm_email_leads.inquiry_type IS
    'dat_hang = đặt hàng | bao_gia = xin báo giá | hoi_thong_tin = hỏi thông tin | khac';
CREATE INDEX idx_crm_email_leads_project_received ON crm_email_leads(project_id, received_at DESC);
CREATE INDEX idx_crm_email_leads_contact_received ON crm_email_leads(contact_id, received_at DESC);
CREATE INDEX idx_crm_email_leads_inquiry_type ON crm_email_leads(project_id, inquiry_type);

INSERT INTO permissions (code, module, name) VALUES
    ('crm.view',   'crm', 'Xem khách liên hệ (CRM)'),
    ('crm.create', 'crm', 'Thêm khách liên hệ / nhận email từ n8n'),
    ('crm.update', 'crm', 'Cập nhật khách liên hệ (trạng thái, phụ trách, ghi chú)'),
    ('crm.delete', 'crm', 'Xoá khách liên hệ / email');
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
  FROM (VALUES
    ('SYSTEM_ADMIN', 'crm.view'), ('SYSTEM_ADMIN', 'crm.create'),
    ('SYSTEM_ADMIN', 'crm.update'), ('SYSTEM_ADMIN', 'crm.delete'),
    ('PROJECT_MANAGER', 'crm.view'), ('PROJECT_MANAGER', 'crm.create'),
    ('PROJECT_MANAGER', 'crm.update'), ('PROJECT_MANAGER', 'crm.delete'),
    ('EXECUTIVE', 'crm.view'),
    ('PRODUCT_OWNER', 'crm.view'), ('PRODUCT_OWNER', 'crm.create'),
    ('PRODUCT_OWNER', 'crm.update'), ('PRODUCT_OWNER', 'crm.delete'),
    ('SCRUM_MASTER', 'crm.view'),
    ('BA', 'crm.view'), ('BA', 'crm.create'), ('BA', 'crm.update')
  ) AS m(role_code, perm_code)
  JOIN roles r       ON r.code = m.role_code
  JOIN permissions p ON p.code = m.perm_code
ON CONFLICT DO NOTHING;
""")


def downgrade() -> None:
    run_sql("""
DELETE FROM permissions WHERE module = 'crm';
DROP TABLE crm_email_leads;
DROP TABLE crm_contacts;
""")
