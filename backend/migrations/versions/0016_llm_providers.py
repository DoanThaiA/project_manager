"""AI Gateway: nhà cung cấp động (Grok, DeepSeek, OpenRouter, Ollama...) thay cho Anthropic / OpenAI cố định

- llm_providers: code (đường dẫn /llm/{code}/v1/...), định dạng API ('openai' = Authorization: Bearer +
  /chat/completions..., 'anthropic' = x-api-key + /messages), base_url GỒM phần phiên bản (vd https://api.x.ai/v1,
  https://generativelanguage.googleapis.com/v1beta/openai), header bổ sung, có tự bật include_usage khi stream không.
  Có sẵn anthropic + openai (is_builtin: không xoá, không đổi code / định dạng).
- llm_provider_keys.provider / llm_models.provider: bỏ CHECK cố định, thành khoá ngoại tới llm_providers(code).
- llm_provider_keys.base_url (ghi đè theo key) cũng gồm phần phiên bản: bản ghi cũ được nối thêm '/v1'.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-05
"""

from collections.abc import Sequence

from alembic import context, op
from sqlalchemy.util import await_only

revision: str = "0016"
down_revision: str | None = "0015"
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
CREATE TABLE llm_providers (
    id             int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code           varchar(30)  NOT NULL,
    name           varchar(100) NOT NULL,
    api_format     varchar(20)  NOT NULL,
    base_url       varchar(255) NOT NULL,
    extra_headers  jsonb        NOT NULL DEFAULT '{}',
    stream_usage   boolean      NOT NULL DEFAULT true,
    is_active      boolean      NOT NULL DEFAULT true,
    is_builtin     boolean      NOT NULL DEFAULT false,
    created_at     timestamptz  NOT NULL DEFAULT now(),
    updated_at     timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT uq_llm_providers_code UNIQUE (code),
    CONSTRAINT ck_llm_providers_code CHECK (code ~ '^[a-z0-9][a-z0-9-]{1,29}$'),
    CONSTRAINT ck_llm_providers_format CHECK (api_format IN ('anthropic', 'openai')),
    CONSTRAINT ck_llm_providers_base_url CHECK (base_url ~ '^https?://')
);
COMMENT ON TABLE llm_providers IS 'Nhà cung cấp AI của gateway; code là đoạn đường dẫn /llm/{code}/v1/...';
COMMENT ON COLUMN llm_providers.api_format IS 'openai: Bearer + /chat/completions; anthropic: x-api-key + /messages';
COMMENT ON COLUMN llm_providers.base_url IS 'Gồm phần phiên bản; gateway gọi {base_url}/chat/completions';
COMMENT ON COLUMN llm_providers.extra_headers IS 'Header gửi kèm mọi request (không đặt key bí mật ở đây)';
COMMENT ON COLUMN llm_providers.stream_usage IS 'Định dạng openai: tự thêm stream_options.include_usage khi stream';
CREATE TRIGGER trg_llm_providers_updated_at BEFORE UPDATE ON llm_providers
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
CREATE TRIGGER trg_llm_providers_audit AFTER INSERT OR UPDATE OR DELETE ON llm_providers
    FOR EACH ROW EXECUTE FUNCTION fn_audit_log();

INSERT INTO llm_providers (code, name, api_format, base_url, is_builtin) VALUES
    ('anthropic', 'Anthropic', 'anthropic', 'https://api.anthropic.com/v1', true),
    ('openai',    'OpenAI',    'openai',    'https://api.openai.com/v1',    true);

ALTER TABLE llm_provider_keys
    DROP CONSTRAINT ck_llm_provider_keys_provider,
    ADD CONSTRAINT fk_llm_provider_keys_provider FOREIGN KEY (provider) REFERENCES llm_providers(code);
ALTER TABLE llm_models
    DROP CONSTRAINT ck_llm_models_provider,
    ADD CONSTRAINT fk_llm_models_provider FOREIGN KEY (provider) REFERENCES llm_providers(code);
ALTER TABLE llm_provider_keys ALTER COLUMN provider TYPE varchar(30);
ALTER TABLE llm_models ALTER COLUMN provider TYPE varchar(30);
ALTER TABLE llm_usage_logs ALTER COLUMN provider TYPE varchar(30);

-- base_url ghi đè theo key: trước đây gateway tự nối '/v1', nay base_url gồm phần phiên bản
UPDATE llm_provider_keys SET base_url = rtrim(base_url, '/') || '/v1' WHERE base_url IS NOT NULL;
COMMENT ON COLUMN llm_provider_keys.base_url IS 'Bỏ trống = base_url của nhà cung cấp; gồm phần phiên bản, vd .../v1';
""")


def downgrade() -> None:
    run_sql("""
UPDATE llm_provider_keys SET base_url = regexp_replace(base_url, '/v1$', '') WHERE base_url IS NOT NULL;
DELETE FROM llm_usage_logs WHERE provider NOT IN ('anthropic', 'openai');
DELETE FROM llm_models WHERE provider NOT IN ('anthropic', 'openai');
DELETE FROM llm_provider_keys WHERE provider NOT IN ('anthropic', 'openai');
ALTER TABLE llm_provider_keys
    DROP CONSTRAINT fk_llm_provider_keys_provider,
    ADD CONSTRAINT ck_llm_provider_keys_provider CHECK (provider IN ('anthropic', 'openai'));
ALTER TABLE llm_models
    DROP CONSTRAINT fk_llm_models_provider,
    ADD CONSTRAINT ck_llm_models_provider CHECK (provider IN ('anthropic', 'openai'));
DROP TABLE llm_providers;
""")
