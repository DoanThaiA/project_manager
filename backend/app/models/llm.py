from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class LlmProviderKey(TimestampMixin, Base):
    """Key thật của nhà cung cấp AI, mã hoá bằng LLM_ENCRYPTION_KEY (services/llm_gateway.py)."""

    __tablename__ = "llm_provider_keys"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(String(20))  # anthropic | openai
    name: Mapped[str] = mapped_column(String(100))
    encrypted_key: Mapped[str] = mapped_column(Text)
    key_hint: Mapped[str] = mapped_column(String(12))
    base_url: Mapped[str | None] = mapped_column(String(255))
    priority: Mapped[int] = mapped_column(SmallInteger, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))


class LlmModel(TimestampMixin, Base):
    """Model được phép gọi qua gateway + giá USD / 1 triệu token."""

    __tablename__ = "llm_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(100))
    input_price: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal(0))
    output_price: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal(0))
    cache_read_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))  # NULL = như input_price
    cache_write_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class LlmClientKey(TimestampMixin, Base):
    """Key gateway cấp cho dự án (pm_llm_...), chỉ lưu SHA-256."""

    __tablename__ = "llm_client_keys"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("projects.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(100))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    key_prefix: Mapped[str] = mapped_column(String(20))
    allowed_models: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)  # rỗng = mọi model đang bật
    monthly_budget_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    rpm_limit: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))


class LlmUsageLog(Base):
    """Usage một request qua gateway; không lưu nội dung prompt / câu trả lời."""

    __tablename__ = "llm_usage_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_key_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("llm_client_keys.id", ondelete="SET NULL"))
    project_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("projects.id", ondelete="SET NULL"))
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str | None] = mapped_column(String(100))
    endpoint: Mapped[str] = mapped_column(String(50))
    provider_key_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("llm_provider_keys.id", ondelete="SET NULL")
    )
    status_code: Mapped[int] = mapped_column(SmallInteger)
    stream: Mapped[bool] = mapped_column(Boolean, default=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)  # không tính phần đọc cache
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
