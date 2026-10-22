from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import CustomerStatus
from app.schemas.common import ORMModel


class CustomerBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    tax_code: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    address: str | None = None
    website: str | None = None
    note: str | None = None


class CustomerCreate(CustomerBase):
    code: str = Field(min_length=1, max_length=30)


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    tax_code: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    address: str | None = None
    website: str | None = None
    note: str | None = None
    status: CustomerStatus | None = None


class CustomerOut(ORMModel):
    id: int
    code: str
    name: str
    tax_code: str | None
    email: str | None
    phone: str | None
    address: str | None
    website: str | None
    status: CustomerStatus
    note: str | None
    created_at: datetime
    updated_at: datetime


class ContactCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=150)
    position: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    is_primary: bool = False


class ContactUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    position: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    is_primary: bool | None = None


class ContactOut(ORMModel):
    id: int
    customer_id: int
    full_name: str
    position: str | None
    email: str | None
    phone: str | None
    is_primary: bool


class ContactOcrOut(BaseModel):
    """Gợi ý điền form người liên hệ từ ảnh danh thiếp."""

    full_name: str | None
    position: str | None
    email: str | None
    phone: str | None
    company: str | None
    text: str
