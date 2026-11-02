from datetime import date, datetime, time
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field

from app.schemas.common import ORMModel
from app.schemas.user import UserBrief


def _to_str(value: Any) -> Any:
    """inet / cidr của asyncpg (IPv4Address, IPv4Network...) -> chuỗi."""
    return str(value) if value is not None else None


IpStr = Annotated[str | None, BeforeValidator(_to_str)]
Reason = Annotated[str, Field(min_length=3, max_length=500, description="Lý do thêm / sửa công (bắt buộc)")]


# ---------------------------------------------------------------- Mạng công ty


class NetworkBrief(ORMModel):
    id: int
    name: str


class NetworkCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    cidr: str = Field(description="IP (113.161.10.20) hoặc dải IP (113.161.10.16/29, 2402:800:1234::/56)")
    is_active: bool = True
    note: str | None = None


class NetworkFromCurrentIp(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    note: str | None = None


class NetworkUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    cidr: str | None = None
    is_active: bool | None = None
    note: str | None = None


class NetworkOut(ORMModel):
    id: int
    name: str
    cidr: Annotated[str, BeforeValidator(_to_str)]
    is_active: bool
    note: str | None
    created_at: datetime
    updated_at: datetime


class MyIpOut(BaseModel):
    ip: str | None
    network: NetworkBrief | None
    x_forwarded_for: str | None = Field(
        default=None, description="Chỉ hiện với attendance.manage, để dò cấu hình proxy"
    )
    client_host: str | None = None


# ---------------------------------------------------------------- Bảng công


class ShiftOut(BaseModel):
    start_time: time
    end_time: time
    break_start: time
    break_end: time
    late_grace_minutes: int
    early_grace_minutes: int
    work_days: list[int]


class RecordOut(ORMModel):
    id: int
    user_id: int
    user: UserBrief | None = None
    work_date: date
    check_in_at: datetime
    check_in_ip: IpStr
    check_in_network: NetworkBrief | None = None
    check_out_at: datetime | None
    check_out_ip: IpStr
    check_out_network: NetworkBrief | None = None
    late_minutes: int
    early_leave_minutes: int
    worked_minutes: int | None
    source: str
    note: str | None
    adjusted_by: int | None
    adjusted_reason: str | None
    # Suy ra khi đọc
    is_late: bool = False
    is_early_leave: bool = False
    missing_checkout: bool = False


class CheckBody(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class TodayOut(BaseModel):
    work_date: date
    is_work_day: bool
    ip: str | None
    network: NetworkBrief | None
    shift: ShiftOut
    record: RecordOut | None
    can_check_in: bool
    can_check_out: bool


class DayOut(BaseModel):
    date: date
    is_work_day: bool
    absent: bool = Field(description="Ngày làm việc đã qua mà không có bản ghi")
    record: RecordOut | None


class MonthOut(BaseModel):
    month: str
    days: list[DayOut]
    present_days: int
    late_count: int
    early_leave_count: int
    missing_checkout_count: int
    absent_days: int
    worked_minutes: int


class RecordCreate(BaseModel):
    user_id: int
    work_date: date
    check_in_time: time = Field(description="Giờ vào (giờ Việt Nam)")
    check_out_time: time | None = None
    note: str | None = Field(default=None, max_length=500)
    adjusted_reason: Reason


class RecordUpdate(BaseModel):
    check_in_time: time | None = None
    check_out_time: time | None = Field(default=None, description="null = xoá giờ về")
    note: str | None = Field(default=None, max_length=500)
    adjusted_reason: Reason


class SummaryRow(BaseModel):
    user: UserBrief
    present_days: int
    late_count: int
    late_minutes: int
    early_leave_count: int
    early_leave_minutes: int
    missing_checkout_count: int
    absent_days: int
    worked_minutes: int


class SummaryOut(BaseModel):
    month: str
    work_days: int = Field(description="Số ngày làm việc của tháng (tính tới hôm qua nếu là tháng hiện tại)")
    rows: list[SummaryRow]


class EventOut(ORMModel):
    id: int
    user: UserBrief | None = None
    action: str
    accepted: bool
    reason: str | None
    ip: IpStr
    network_id: int | None
    user_agent: str | None
    created_at: datetime
