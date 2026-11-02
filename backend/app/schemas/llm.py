from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, HttpUrl

from app.schemas.common import ORMModel

Provider = Literal["anthropic", "openai"]
Price = Annotated[float, Field(ge=0, le=100000, description="USD / 1 triệu token")]


# ---------------------------------------------------------------- Key nhà cung cấp


class ProviderKeyCreate(BaseModel):
    provider: Provider
    name: str = Field(min_length=1, max_length=100)
    api_key: str = Field(min_length=10, max_length=500, description="Key thật; chỉ gửi lên, không bao giờ trả lại")
    base_url: HttpUrl | None = Field(default=None, description="Bỏ trống = endpoint chính thức")
    priority: int = Field(default=0, ge=0, le=100, description="Cao hơn được dùng trước")
    is_active: bool = True


class ProviderKeyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    api_key: str | None = Field(default=None, min_length=10, max_length=500, description="Đổi sang key mới")
    base_url: HttpUrl | None = None
    priority: int | None = Field(default=None, ge=0, le=100)
    is_active: bool | None = None
    reset_cooldown: bool = Field(default=False, description="Cho key dùng lại ngay, xoá lỗi gần nhất")


class ProviderKeyOut(ORMModel):
    id: int
    provider: str
    name: str
    key_hint: str
    base_url: str | None
    priority: int
    is_active: bool
    cooldown_until: datetime | None
    last_used_at: datetime | None
    last_error: str | None
    last_error_at: datetime | None
    created_at: datetime


class ProviderKeyTestOut(BaseModel):
    ok: bool
    status_code: int | None
    message: str


# ---------------------------------------------------------------- Model


class ModelIn(BaseModel):
    provider: Provider
    model: str = Field(min_length=1, max_length=100, description="Đúng tên model của nhà cung cấp")
    input_price: Price = 0
    output_price: Price = 0
    cache_read_price: Price | None = Field(default=None, description="Bỏ trống = như giá input")
    cache_write_price: Price | None = Field(default=None, description="Bỏ trống = như giá input")
    is_active: bool = True


class ModelOut(ORMModel):
    id: int
    provider: str
    model: str
    input_price: float
    output_price: float
    cache_read_price: float | None
    cache_write_price: float | None
    is_active: bool


# ---------------------------------------------------------------- Key dự án


class ClientKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    project_id: int | None = None
    allowed_models: list[str] = Field(default_factory=list, description="Rỗng = mọi model đang bật")
    monthly_budget_usd: float | None = Field(
        default=None, ge=0, description="Hạn mức USD / tháng; null = không giới hạn"
    )
    rpm_limit: int | None = Field(default=None, gt=0, description="Request / phút; null = không giới hạn")
    expires_at: datetime | None = None


class ClientKeyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    project_id: int | None = None
    allowed_models: list[str] | None = None
    monthly_budget_usd: float | None = Field(default=None, ge=0)
    rpm_limit: int | None = Field(default=None, gt=0)
    expires_at: datetime | None = None


class ProjectBrief(ORMModel):
    id: int
    key: str
    name: str


class ClientKeyOut(ORMModel):
    id: int
    name: str
    project_id: int | None
    project: ProjectBrief | None = None
    key_prefix: str
    allowed_models: list[str]
    monthly_budget_usd: float | None
    rpm_limit: int | None
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    spent_this_month: float = 0


class ClientKeyCreated(ClientKeyOut):
    key: str = Field(description="Key đầy đủ, CHỈ hiện một lần")


# ---------------------------------------------------------------- Sử dụng


class UsageTotals(BaseModel):
    requests: int = 0
    errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0


class UsageByKey(UsageTotals):
    client_key_id: int | None
    name: str | None
    project: ProjectBrief | None = None
    monthly_budget_usd: float | None = None


class UsageByModel(UsageTotals):
    provider: str
    model: str | None


class UsageByDay(UsageTotals):
    date: date


class UsageSummary(BaseModel):
    month: str
    total: UsageTotals
    by_key: list[UsageByKey]
    by_model: list[UsageByModel]
    by_day: list[UsageByDay]


class UsageLogOut(ORMModel):
    id: int
    created_at: datetime
    client_key_id: int | None
    client_key_name: str | None = None
    provider: str
    model: str | None
    endpoint: str
    status_code: int
    stream: bool
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    latency_ms: int | None
    error: str | None


class GatewayStatus(BaseModel):
    enabled: bool = Field(description="Đã đặt LLM_ENCRYPTION_KEY")
    public_base_url: str = Field(description="Gốc URL cho base_url của SDK, vd https://<domain>/llm")
