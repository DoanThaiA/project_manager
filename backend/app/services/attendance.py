"""Chấm công theo IP: so IP với mạng công ty, tính phút đi muộn / về sớm / giờ làm theo ca cố định (config)."""

import ipaddress
from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import AttendanceNetwork, AttendanceRecord

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


def is_work_day(day: date) -> bool:
    return day.isoweekday() in settings.attendance_work_days


def _minutes(delta: timedelta) -> int:
    return max(0, int(delta.total_seconds() // 60))


def late_minutes(day: date, check_in: datetime) -> int:
    return _minutes(check_in - at_time(day, settings.attendance_start_time))


def early_leave_minutes(day: date, check_out: datetime) -> int:
    return _minutes(at_time(day, settings.attendance_end_time) - check_out)


def worked_minutes(day: date, check_in: datetime, check_out: datetime) -> int:
    """Giờ ra - giờ vào, trừ phần trùng giờ nghỉ trưa."""
    total = check_out - check_in
    break_start = at_time(day, settings.attendance_break_start)
    break_end = at_time(day, settings.attendance_break_end)
    overlap = min(check_out, break_end) - max(check_in, break_start)
    return _minutes(total - max(overlap, timedelta(0)))


def recompute(record: AttendanceRecord) -> None:
    """Tính lại số phút từ giờ vào / ra hiện tại của bản ghi."""
    record.late_minutes = late_minutes(record.work_date, record.check_in_at)
    if record.check_out_at is None:
        record.early_leave_minutes, record.worked_minutes = 0, None
    else:
        record.early_leave_minutes = early_leave_minutes(record.work_date, record.check_out_at)
        record.worked_minutes = worked_minutes(record.work_date, record.check_in_at, record.check_out_at)


def flags(record: AttendanceRecord, today: date) -> dict[str, bool]:
    """Trạng thái suy ra khi đọc (không lưu), nên đổi số phút cho phép không làm dữ liệu cũ sai."""
    return {
        "is_late": record.late_minutes > settings.attendance_late_grace_minutes,
        "is_early_leave": record.check_out_at is not None
        and record.early_leave_minutes > settings.attendance_early_grace_minutes,
        "missing_checkout": record.check_out_at is None and record.work_date < today,
    }


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
