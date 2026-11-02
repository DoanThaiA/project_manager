"""Chấm công theo IP: so IP với mạng công ty, tính phút đi muộn / về sớm / giờ làm theo ca của user."""

import ipaddress
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import AttendanceNetwork, AttendanceRecord, AttendanceShift, AttendanceShiftDay, User

# Việt Nam không có giờ mùa hè: múi giờ cố định, không cần dữ liệu tzdata (Windows, image slim)
VN_TZ = timezone(timedelta(hours=7))

# Dải quá rộng thì cả một nhà mạng chấm được -> chặn
MIN_PREFIX = {4: 24, 6: 48}


def local(at: datetime) -> datetime:
    return at.astimezone(VN_TZ)


def work_date_of(at: datetime) -> date:
    return local(at).date()


def at_time(day: date, t: time) -> datetime:
    return datetime.combine(day, t, tzinfo=VN_TZ)


def schedule_of(shift: AttendanceShift, day: date) -> AttendanceShiftDay | None:
    """Lịch của ca trong ngày `day` (theo thứ); None = ngày nghỉ của ca."""
    return next((d for d in shift.days if d.weekday == day.isoweekday()), None)


def is_work_day(day: date, shift: AttendanceShift) -> bool:
    return schedule_of(shift, day) is not None


def _minutes(delta: timedelta) -> int:
    return max(0, int(delta.total_seconds() // 60))


def late_minutes(day: date, check_in: datetime, sched: AttendanceShiftDay | None) -> int:
    """Ngày nghỉ (không có lịch) thì không tính muộn."""
    return _minutes(check_in - at_time(day, sched.start_time)) if sched else 0


def early_leave_minutes(day: date, check_out: datetime, sched: AttendanceShiftDay | None) -> int:
    return _minutes(at_time(day, sched.end_time) - check_out) if sched else 0


def worked_minutes(day: date, check_in: datetime, check_out: datetime, sched: AttendanceShiftDay | None) -> int:
    """Giờ ra - giờ vào, trừ phần trùng giờ nghỉ trưa của ngày đó (nếu có)."""
    total = check_out - check_in
    if sched is None or sched.break_start is None or sched.break_end is None:
        return _minutes(total)
    overlap = min(check_out, at_time(day, sched.break_end)) - max(check_in, at_time(day, sched.break_start))
    return _minutes(total - max(overlap, timedelta(0)))


def recompute(record: AttendanceRecord, shift: AttendanceShift) -> None:
    """Tính lại số phút + số công từ giờ vào / ra hiện tại của bản ghi, theo lịch của ca trong ngày đó.
    Công: có đủ giờ vào + giờ về trong ngày làm việc của ca thì được công của ngày (đi muộn / về sớm không trừ)."""
    sched = schedule_of(shift, record.work_date)
    record.shift_id = shift.id
    record.late_minutes = late_minutes(record.work_date, record.check_in_at, sched)
    if record.check_out_at is None:
        record.early_leave_minutes, record.worked_minutes, record.credit = 0, None, Decimal(0)
    else:
        record.early_leave_minutes = early_leave_minutes(record.work_date, record.check_out_at, sched)
        record.worked_minutes = worked_minutes(record.work_date, record.check_in_at, record.check_out_at, sched)
        record.credit = sched.credit if sched else Decimal(0)


def flags(record: AttendanceRecord, today: date, shift: AttendanceShift) -> dict[str, bool]:
    """Trạng thái suy ra khi đọc (không lưu), nên đổi số phút cho phép không làm dữ liệu cũ sai."""
    return {
        "is_late": record.late_minutes > shift.late_grace_minutes,
        "is_early_leave": record.check_out_at is not None and record.early_leave_minutes > shift.early_grace_minutes,
        "missing_checkout": record.check_out_at is None and record.work_date < today,
    }


class Shifts:
    """Toàn bộ ca (vài dòng, kèm lịch) nạp một lần cho mỗi request: tra theo id, ca mặc định, ca của user."""

    def __init__(self, shifts: list[AttendanceShift]):
        self.by_id = {s.id: s for s in shifts}
        self.default = next(s for s in shifts if s.is_default)

    def of_user(self, user: User) -> AttendanceShift:
        return self.by_id.get(user.attendance_shift_id) or self.default

    def of_record(self, record: AttendanceRecord) -> AttendanceShift:
        return self.by_id.get(record.shift_id) or self.default


async def load_shifts(db: AsyncSession) -> Shifts:
    return Shifts(list(await db.scalars(select(AttendanceShift).order_by(AttendanceShift.id))))


async def match_network(db: AsyncSession, ip: str | None) -> AttendanceNetwork | None:
    """Mạng công ty đang bật chứa IP này (hẹp nhất trước)."""
    if ip is None:
        return None
    return await db.scalar(
        select(AttendanceNetwork)
        .where(AttendanceNetwork.is_active, AttendanceNetwork.cidr.op(">>=")(cast(ip, INET)))
        .order_by(func.masklen(AttendanceNetwork.cidr).desc())
        .limit(1)
    )


def normalize_cidr(value: str) -> str:
    """'113.161.10.20' -> '113.161.10.20/32'; '1.2.3.4/24' -> '1.2.3.0/24'. Chặn dải quá rộng / IP nội bộ."""
    try:
        net = ipaddress.ip_network(value.strip(), strict=False)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"IP / dải IP không hợp lệ: {value}") from exc
    if net.prefixlen < MIN_PREFIX[net.version]:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Dải IP quá rộng: IPv{net.version} tối thiểu /{MIN_PREFIX[net.version]}",
        )
    # Server không bao giờ thấy IP nội bộ của client thật; máy dev bật ATTENDANCE_ALLOW_PRIVATE_NETWORKS để test
    if not net.is_global and not settings.attendance_allow_private_networks:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{net} là IP nội bộ, hãy nhập IP công cộng của văn phòng",
        )
    return str(net)


def network_of_ip(ip: str) -> str:
    """IP đang dùng -> CIDR để thêm vào danh sách: IPv4 /32, IPv6 /64 (mỗi máy một địa chỉ trong cùng prefix)."""
    addr = ipaddress.ip_address(ip)
    prefix = 32 if addr.version == 4 else 64
    return str(ipaddress.ip_network(f"{addr}/{prefix}", strict=False))
