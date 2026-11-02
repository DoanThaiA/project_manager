"""AI Gateway tối giản: quản lý key Anthropic / OpenAI, cấp key cho dự án kèm hạn mức, ghi usage (docs/LLM_GATEWAY.md)

- llm_provider_keys: key thật của nhà cung cấp, MÃ HOÁ (Fernet, khoá ở biến môi trường LLM_ENCRYPTION_KEY).
  Một nhà cung cấp có nhiều key: chọn theo độ ưu tiên, key lỗi 429 / 5xx tạm nghỉ (cooldown_until) rồi thử key khác.
  Không gắn fn_audit_log (sẽ chép encrypted_key vào nhật ký): thêm / sửa / xoá key ghi activity_logs từ API.
- llm_models: model được phép gọi + giá USD / 1 triệu token (tính chi phí). Model không có ở đây thì gateway từ chối.
- llm_client_keys: key cấp cho dự án (pm_llm_...), chỉ lưu SHA-256. allowed_models rỗng = mọi model đang bật;
  monthly_budget_usd NULL = không giới hạn; rpm_limit NULL = không giới hạn.
- llm_usage_logs: mỗi request một dòng (token, chi phí, độ trễ, lỗi). KHÔNG lưu nội dung prompt / câu trả lời.
- Quyền llm.manage (quản trị) / llm.view (xem thống kê).

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-04
"""

from collections.abc import Sequence

from alembic import context, op
from sqlalchemy.util import await_only

revision: str = "0015"
down_revision: str | None = "0014"
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
CREATE TABLE llm_provider_keys (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider        varchar(20)  NOT NULL,
    name            varchar(100) NOT NULL,
    encrypted_key   text         NOT NULL,
    key_hint        varchar(12)  NOT NULL,
    base_url        varchar(255),
    priority        smallint     NOT NULL DEFAULT 0,
    is_active       boolean      NOT NULL DEFAULT true,
    cooldown_until  timestamptz,
    last_used_at    timestamptz,
    last_error      text,
    last_error_at   timestamptz,
    created_by      bigint REFERENCES users(id) ON DELETE SET NULL,
    created_at      timestamptz  NOT NULL DEFAULT now(),
    updated_at      timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT ck_llm_provider_keys_provider CHECK (provider IN ('anthropic', 'openai'))
);
COMMENT ON TABLE llm_provider_keys IS 'Key nhà cung cấp AI, mã hoá bằng LLM_ENCRYPTION_KEY';
COMMENT ON COLUMN llm_provider_keys.key_hint IS '4 ký tự cuối của key để nhận biết, vd ••••a1b2';
COMMENT ON COLUMN llm_provider_keys.base_url IS 'Bỏ trống = endpoint chính thức của nhà cung cấp';
CREATE TRIGGER trg_llm_provider_keys_updated_at BEFORE UPDATE ON llm_provider_keys
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

CREATE TABLE llm_models (
    id                      int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider                varchar(20)   NOT NULL,
    model                   varchar(100)  NOT NULL,
    input_price             numeric(10,4) NOT NULL DEFAULT 0,
    output_price            numeric(10,4) NOT NULL DEFAULT 0,
    cache_read_price        numeric(10,4),
    cache_write_price       numeric(10,4),
    is_active               boolean       NOT NULL DEFAULT true,
    created_at              timestamptz   NOT NULL DEFAULT now(),
    updated_at              timestamptz   NOT NULL DEFAULT now(),
    CONSTRAINT uq_llm_models_provider_model UNIQUE (provider, model),
    CONSTRAINT ck_llm_models_provider CHECK (provider IN ('anthropic', 'openai')),
    CONSTRAINT ck_llm_models_price CHECK (
        input_price >= 0 AND output_price >= 0
        AND coalesce(cache_read_price, 0) >= 0 AND coalesce(cache_write_price, 0) >= 0
    )
);
COMMENT ON TABLE llm_models IS 'Model được phép gọi qua gateway; giá USD / 1 triệu token';
COMMENT ON COLUMN llm_models.model IS 'Đúng tên model gửi lên nhà cung cấp, vd claude-sonnet-5-5';
COMMENT ON COLUMN llm_models.cache_read_price IS 'NULL = tính như input_price';
CREATE TRIGGER trg_llm_models_updated_at BEFORE UPDATE ON llm_models
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
CREATE TRIGGER trg_llm_models_audit AFTER INSERT OR UPDATE OR DELETE ON llm_models
    FOR EACH ROW EXECUTE FUNCTION fn_audit_log();

CREATE TABLE llm_client_keys (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id          bigint REFERENCES projects(id) ON DELETE SET NULL,
    name                varchar(100)  NOT NULL,
    key_hash            varchar(64)   NOT NULL,
    key_prefix          varchar(20)   NOT NULL,
    allowed_models      text[]        NOT NULL DEFAULT '{}',
    monthly_budget_usd  numeric(12,2),
    rpm_limit           int,
    expires_at          timestamptz,
    revoked_at          timestamptz,
    last_used_at        timestamptz,
    created_by          bigint REFERENCES users(id) ON DELETE SET NULL,
    created_at          timestamptz   NOT NULL DEFAULT now(),
    updated_at          timestamptz   NOT NULL DEFAULT now(),
    CONSTRAINT uq_llm_client_keys_hash UNIQUE (key_hash),
    CONSTRAINT ck_llm_client_keys_budget CHECK (monthly_budget_usd IS NULL OR monthly_budget_usd >= 0),
    CONSTRAINT ck_llm_client_keys_rpm CHECK (rpm_limit IS NULL OR rpm_limit > 0)
);
COMMENT ON TABLE llm_client_keys IS 'Key gateway cấp cho dự án (pm_llm_...), chỉ lưu SHA-256';
COMMENT ON COLUMN llm_client_keys.allowed_models IS 'Rỗng = mọi model đang bật';
COMMENT ON COLUMN llm_client_keys.monthly_budget_usd IS 'Hạn mức USD / tháng (giờ Việt Nam); NULL = không giới hạn';
CREATE TRIGGER trg_llm_client_keys_updated_at BEFORE UPDATE ON llm_client_keys
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

CREATE TABLE llm_usage_logs (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_key_id       bigint REFERENCES llm_client_keys(id) ON DELETE SET NULL,
    project_id          bigint REFERENCES projects(id) ON DELETE SET NULL,
    provider            varchar(20)   NOT NULL,
    model               varchar(100),
    endpoint            varchar(50)   NOT NULL,
    provider_key_id     bigint REFERENCES llm_provider_keys(id) ON DELETE SET NULL,
    status_code         smallint      NOT NULL,
    stream              boolean       NOT NULL DEFAULT false,
    input_tokens        int           NOT NULL DEFAULT 0,
    output_tokens       int           NOT NULL DEFAULT 0,
    cache_read_tokens   int           NOT NULL DEFAULT 0,
    cache_write_tokens  int           NOT NULL DEFAULT 0,
    cost_usd            numeric(12,6) NOT NULL DEFAULT 0,
    latency_ms          int,
    error               text,
    created_at          timestamptz   NOT NULL DEFAULT now()
);
COMMENT ON TABLE llm_usage_logs IS 'Usage từng request qua gateway; không lưu nội dung prompt / câu trả lời';
COMMENT ON COLUMN llm_usage_logs.input_tokens IS 'Token vào KHÔNG tính phần đọc cache';
CREATE INDEX idx_llm_usage_logs_client ON llm_usage_logs(client_key_id, created_at DESC);
CREATE INDEX idx_llm_usage_logs_project ON llm_usage_logs(project_id, created_at DESC);
CREATE INDEX idx_llm_usage_logs_created ON llm_usage_logs(created_at DESC);

INSERT INTO permissions (code, module, name) VALUES
    ('llm.manage', 'llm', 'Quản lý AI Gateway (key nhà cung cấp, model, key dự án)'),
    ('llm.view',   'llm', 'Xem sử dụng & chi phí AI Gateway');
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
  FROM (VALUES
    ('SYSTEM_ADMIN', 'llm.manage'), ('SYSTEM_ADMIN', 'llm.view'),
    ('PROJECT_MANAGER', 'llm.view'),
    ('EXECUTIVE', 'llm.view')
  ) AS m(role_code, perm_code)
  JOIN roles r       ON r.code = m.role_code
  JOIN permissions p ON p.code = m.perm_code
ON CONFLICT DO NOTHING;
""")


def downgrade() -> None:
    run_sql("""
DELETE FROM permissions WHERE module = 'llm';
DROP TABLE llm_usage_logs;
DROP TABLE llm_client_keys;
DROP TABLE llm_models;
DROP TABLE llm_provider_keys;
""")
