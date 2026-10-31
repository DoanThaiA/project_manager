from datetime import datetime, timedelta, timezone
from decimal import Decimal
from email.utils import parseaddr
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, BeforeValidator, EmailStr, Field

from app.models.enums import CrmContactStatus, CrmInquiryType
from app.schemas.common import ORMModel

VN_TZ = timezone(timedelta(hours=7))


def _clip(max_len: int | None = None) -> BeforeValidator:
    """Chuỗi AI trích xuất: bỏ khoảng trắng, "" -> None, cắt bớt cho vừa cột (không báo lỗi để n8n không mất email)."""

    def convert(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return (text[:max_len] if max_len else text) or None

    return BeforeValidator(convert)


def _sender_email(value: Any) -> Any:
    """'Nguyễn Văn A <A@Mail.com>' -> 'a@mail.com'."""
    if isinstance(value, str):
        return (parseaddr(value)[1] or value).strip().lower()
    return value


def _inquiry_type(value: Any) -> Any:
    """Giá trị lạ / trống từ AI -> 'khac'."""
    if value is None or (isinstance(value, str) and value.strip().lower() not in CrmInquiryType):
        return CrmInquiryType.khac
    return value.strip().lower() if isinstance(value, str) else value


def _confidence(value: Any) -> Any:
    """'' -> None; ngoài [0, 1] thì kẹp lại."""
    if value is None or value == "":
        return None
    try:
        return min(max(Decimal(str(value)), Decimal(0)), Decimal(1))
    except ArithmeticError:
        return None


def _aware(value: datetime) -> datetime:
    """Thời điểm không có múi giờ -> coi là giờ Việt Nam."""
    if value.tzinfo is None:
        return value.replace(tzinfo=VN_TZ)
    return value


Str50 = Annotated[str | None, _clip(50)]
Str100 = Annotated[str | None, _clip(100)]
Str255 = Annotated[str | None, _clip(255)]
Str320 = Annotated[str | None, _clip(320)]
LongStr = Annotated[str | None, _clip()]
SenderEmail = Annotated[EmailStr, BeforeValidator(_sender_email)]


class CrmEmailIngest(BaseModel):
    """Payload n8n gửi sang: 1 email khách liên hệ (tên trường giống bảng kpacking_email_leads)."""

    email_message_id: str = Field(min_length=1, max_length=100, description="Mã email Gmail, chống trùng")
    email_thread_id: Str100 = None
    received_at: Annotated[datetime, AfterValidator(_aware)] = Field(
        description="ISO 8601; không có múi giờ thì coi là giờ Việt Nam"
    )
    subject: Annotated[str | None, _clip(998)] = None
    content: LongStr = None

    customer_name: Str255 = None
    customer_email: SenderEmail = Field(description="Email người gửi (header Gmail)")
    contact_email: Str320 = None
    phone: Str50 = None
    company: Str255 = None
    address: LongStr = None

    inquiry_type: Annotated[CrmInquiryType, BeforeValidator(_inquiry_type)] = CrmInquiryType.khac
    product_type: Str255 = None
    quantity: Str255 = None
    specifications: LongStr = None
    budget: Str255 = None
    deadline: Str255 = None
    summary: LongStr = None
    ai_confidence: Annotated[Decimal | None, BeforeValidator(_confidence)] = None
    source: Annotated[str, _clip(30)] = "gmail"


class CrmIngestOut(BaseModel):
    lead_id: int
    contact_id: int
    created: bool = Field(description="false = email đã nhận trước đó (n8n gửi lại), không tạo mới")


class CrmEmailLeadOut(ORMModel):
    id: int
    project_id: int
    contact_id: int
    email_message_id: str
    email_thread_id: str | None
    received_at: datetime
    subject: str | None
    content: str | None
    customer_name: str | None
    customer_email: str
    contact_email: str | None
    phone: str | None
    company: str | None
    address: str | None
    inquiry_type: CrmInquiryType
    product_type: str | None
    quantity: str | None
    specifications: str | None
    budget: str | None
    deadline: str | None
    summary: str | None
    ai_confidence: Decimal | None
    source: str
    created_at: datetime


class CrmContactCreate(BaseModel):
    email: EmailStr
    full_name: Str255 = None
    contact_email: Str320 = None
    phone: Str50 = None
    company: Str255 = None
    address: LongStr = None
    status: CrmContactStatus = CrmContactStatus.new
    assignee_id: int | None = None
    note: LongStr = None


class CrmContactUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: Str255 = None
    contact_email: Str320 = None
    phone: Str50 = None
    company: Str255 = None
    address: LongStr = None
    status: CrmContactStatus | None = None
    assignee_id: int | None = None
    note: LongStr = None


class CrmContactOut(ORMModel):
    id: int
    project_id: int
    email: str
    full_name: str | None
    contact_email: str | None
    phone: str | None
    company: str | None
    address: str | None
    status: CrmContactStatus
    assignee_id: int | None
    note: str | None
    source: str
    created_by: int | None
    created_at: datetime
    updated_at: datetime
    email_count: int = Field(default=0, description="Số email đã nhận")
    last_contact_at: datetime | None = Field(default=None, description="Thời điểm email gần nhất")
    last_inquiry_type: CrmInquiryType | None = Field(default=None, description="Loại nhu cầu của email gần nhất")


class CrmStats(BaseModel):
    total: int
    by_status: dict[CrmContactStatus, int]
    emails_7d: int = Field(description="Số email nhận trong 7 ngày qua")
    unassigned: int = Field(description="Khách đang mở (chưa chốt / không thành / spam) chưa có người phụ trách")
