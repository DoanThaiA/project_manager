from datetime import date, datetime, time
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, BeforeValidator, Field, model_validator

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


# ---------------------------------------------------------------- Ca làm việc


class ShiftBrief(ORMModel):
    id: int
    name: str


class ShiftDay(ORMModel):
    """Lịch của ca trong một thứ. Thứ không có trong danh sách = ngày nghỉ của ca."""

    weekday: int = Field(ge=1, le=7, description="ISO: 1 = thứ 2 ... 7 = chủ nhật")
    start_time: time
    end_time: time
    break_start: time | None = None
    break_end: time | None = None
    credit: float = Field(default=1, gt=0, le=1, description="Số công của ngày (vd T7 làm buổi sáng = 0,5)")

    @model_validator(mode="after")
    def _check_times(self):
        if not self.start_time < self.end_time:
            raise ValueError("Giờ về phải sau giờ vào")
        if (self.break_start is None) != (self.break_end is None):
            raise ValueError("Nhập đủ giờ bắt đầu và kết thúc nghỉ trưa, hoặc bỏ trống cả hai")
        if (
            self.break_start
            and self.break_end
            and not (self.start_time <= self.break_start < self.break_end <= self.end_time)
        ):
            raise ValueError("Giờ nghỉ trưa phải nằm trong ca")
        return self


def _unique_weekdays(days: list[ShiftDay]) -> list[ShiftDay]:
    if len({d.weekday for d in days}) != len(days):
        raise ValueError("Mỗi thứ chỉ khai báo một lần")
    return sorted(days, key=lambda d: d.weekday)


ShiftDays = Annotated[list[ShiftDay], AfterValidator(_unique_weekdays), Field(min_length=1)]


class ShiftOut(ORMModel):
    id: int
    name: str
    late_grace_minutes: int
    early_grace_minutes: int
    is_default: bool
    days: list[ShiftDay]
    user_count: int = Field(default=0, description="Số user được gán ca này (không tính user dùng ca mặc định)")


class ShiftIn(BaseModel):
    """Tạo / sửa ca: gửi đủ các trường (form sửa ca gửi toàn bộ, kể cả lịch 7 ngày)."""

    name: str = Field(min_length=1, max_length=100)
    late_grace_minutes: int = Field(default=5, ge=0, le=240)
    early_grace_minutes: int = Field(default=0, ge=0, le=240)
    is_default: bool = False
    days: ShiftDays


class ShiftAssign(BaseModel):
    shift_id: int | None = Field(description="null = dùng ca mặc định")


# ---------------------------------------------------------------- Bảng công


class RecordOut(ORMModel):
    id: int
    user_id: int
    user: UserBrief | None = None
    work_date: date
    shift_id: int
    shift: ShiftBrief | None = None
    check_in_at: datetime
    check_in_ip: IpStr
    check_in_network: NetworkBrief | None = None
    check_out_at: datetime | None
    check_out_ip: IpStr
    check_out_network: NetworkBrief | None = None
    late_minutes: int
    early_leave_minutes: int
    worked_minutes: int | None
    credit: float = Field(description="Số công của ngày (0 khi thiếu check-out / ngày nghỉ)")
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
    schedule: ShiftDay | None = Field(description="Lịch hôm nay theo ca; null = ngày nghỉ")
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
    shift: ShiftBrief = Field(description="Ca hiện tại của tôi")
    days: list[DayOut]
    present_days: int
    late_count: int
    early_leave_count: int
    missing_checkout_count: int
    absent_days: int
    worked_minutes: int
    credit: float = Field(description="Số công thực tế")
    expected_credit: float = Field(description="Số công chuẩn của các ngày làm việc đã qua")


class RecordCreate(BaseModel):
    user_id: int
    work_date: date
    check_in_time: time = Field(description="Giờ vào (giờ Việt Nam)")
    check_out_time: time | None = None
    shift_id: int | None = Field(default=None, description="Bỏ trống = ca hiện tại của nhân viên")
    note: str | None = Field(default=None, max_length=500)
    adjusted_reason: Reason


class RecordUpdate(BaseModel):
    check_in_time: time | None = None
    check_out_time: time | None = Field(default=None, description="null = xoá giờ về")
    shift_id: int | None = Field(default=None, description="Đổi ca áp dụng cho ngày này")
    note: str | None = Field(default=None, max_length=500)
    adjusted_reason: Reason


class SummaryRow(BaseModel):
    user: UserBrief
    shift: ShiftBrief = Field(description="Ca đang áp dụng (ca được gán, hoặc ca mặc định)")
    assigned_shift_id: int | None = Field(description="Ca được gán riêng; null = dùng ca mặc định")
    work_days: int = Field(description="Số ngày làm việc đã qua trong tháng theo ca của người này")
    present_days: int
    late_count: int
    late_minutes: int
    early_leave_count: int
    early_leave_minutes: int
    missing_checkout_count: int
    absent_days: int
    worked_minutes: int
    credit: float = Field(description="Số công thực tế")
    expected_credit: float = Field(description="Số công chuẩn của các ngày làm việc đã qua")


class SummaryOut(BaseModel):
    month: str
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


class UserShiftOut(BaseModel):
    user_id: int
    assigned_shift_id: int | None
    shift: ShiftBrief
