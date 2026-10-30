from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    expires_days: int = Field(default=90, ge=1, le=365)


class ApiTokenOut(ORMModel):
    id: int
    name: str
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiTokenCreated(ApiTokenOut):
    token: str = Field(description="Chỉ hiện một lần, không lưu lại được")
