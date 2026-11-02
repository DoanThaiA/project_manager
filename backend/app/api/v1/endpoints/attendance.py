"""Chấm công theo IP mạng công ty: check-in / check-out chỉ được chấp nhận từ IP văn phòng (docs/ATTENDANCE.md)."""

import csv
import io
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import and_, cast, exists, func, or_, select
from sqlalchemy.dialects.postgresql import CIDR
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, get_current_user, has_permission, oauth2_scheme, require_permission
from app.core.config import settings
from app.core.security import PAT_PREFIX
from app.db.session import get_db
from app.models import (
    AttendanceEvent,
    AttendanceNetwork,
    AttendanceRecord,
    Permission,
    User,
    UserRole,
    role_permissions,
)
from app.models.enums import UserStatus
from app.schemas.attendance import (
    CheckBody,
    DayOut,
    EventOut,
    MonthOut,
    MyIpOut,
    NetworkBrief,
    NetworkCreate,
    NetworkFromCurrentIp,
    NetworkOut,
    NetworkUpdate,
    RecordCreate,
    RecordOut,
    RecordUpdate,
    ShiftOut,
    SummaryOut,
    SummaryRow,
    TodayOut,
)
from app.schemas.common import Page
from app.schemas.user import UserBrief
from app.services.attendance import (
    at_time,
    flags,
    is_work_day,
    late_minutes,
    match_network,
    network_of_ip,
    normalize_cidr,
    recompute,
    work_date_of,
)
from app.services.common import not_found

router = APIRouter()

MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
REJECT_MESSAGES = {
    "api_token": "Không chấm công bằng token truy cập (PAT), hãy đăng nhập trên web",
    "outside_network": "Bạn đang không dùng mạng công ty (IP {ip}). Hãy kết nối Wi-Fi văn phòng rồi thử lại.",
}


# ---------------------------------------------------------------- Tiện ích


async def _db_now(db: AsyncSession) -> datetime:
    """Giờ chấm lấy theo database, không theo máy client."""
    return await db.scalar(select(func.now()))


def _shift() -> ShiftOut:
    return ShiftOut(
        start_time=settings.attendance_start_time,
        end_time=settings.attendance_end_time,
        break_start=settings.attendance_break_start,
        break_end=settings.attendance_break_end,
        late_grace_minutes=settings.attendance_late_grace_minutes,
        early_grace_minutes=settings.attendance_early_grace_minutes,
        work_days=settings.attendance_work_days,
    )


def _month_range(month: str) -> tuple[date, date]:
    start = date(int(month[:4]), int(month[5:7]), 1)
    end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return start, end


async def _user_briefs(db: AsyncSession, ids: set[int]) -> dict[int, UserBrief]:
    if not ids:
        return {}
    users = await db.scalars(select(User).where(User.id.in_(ids)))
    return {u.id: UserBrief.model_validate(u) for u in users}


async def _record_outs(
    db: AsyncSession, records: list[AttendanceRecord], today: date, with_user: bool = False
) -> list[RecordOut]:
    network_ids = {r.check_in_network_id for r in records} | {r.check_out_network_id for r in records}
    network_ids.discard(None)
    networks = {}
    if network_ids:
        rows = await db.scalars(select(AttendanceNetwork).where(AttendanceNetwork.id.in_(network_ids)))
        networks = {n.id: NetworkBrief.model_validate(n) for n in rows}
    users = await _user_briefs(db, {r.user_id for r in records}) if with_user else {}
    return [
        RecordOut.model_validate(r).model_copy(
            update={
                **flags(r, today),
                "user": users.get(r.user_id),
                "check_in_network": networks.get(r.check_in_network_id),
                "check_out_network": networks.get(r.check_out_network_id),
            }
        )
        for r in records
    ]


async def _record_out(db: AsyncSession, record: AttendanceRecord, today: date) -> RecordOut:
    return (await _record_outs(db, [record], today, with_user=True))[0]


def _tally(records: list[AttendanceRecord], start: date, end: date, today: date, since: date) -> dict:
    """Tổng hợp một người trong [start, end]: vắng = ngày làm việc đã qua (từ ngày tạo tài khoản) không có bản ghi."""
    by_date = {r.work_date for r in records}
    absent: list[date] = []
    day = max(start, since)
    while day <= end and day < today:
        if is_work_day(day) and day not in by_date:
            absent.append(day)
        day += timedelta(days=1)
    marks = [flags(r, today) for r in records]
    return {
        "present_days": len(records),
        "late_count": sum(m["is_late"] for m in marks),
        "late_minutes": sum(r.late_minutes for r, m in zip(records, marks, strict=True) if m["is_late"]),
        "early_leave_count": sum(m["is_early_leave"] for m in marks),
        "early_leave_minutes": sum(
            r.early_leave_minutes for r, m in zip(records, marks, strict=True) if m["is_early_leave"]
        ),
        "missing_checkout_count": sum(m["missing_checkout"] for m in marks),
        "absent_days": len(absent),
        "absent": set(absent),
        "worked_minutes": sum(r.worked_minutes or 0 for r in records),
    }


async def _reject_if_needed(
    db: AsyncSession,
    request: Request,
    user: User,
    action: str,
    token: str,
    ip: str | None,
    network: AttendanceNetwork | None,
) -> None:
    """Dùng PAT / ngoài mạng công ty -> ghi event bị từ chối rồi trả 403."""
    reason = "api_token" if token.startswith(PAT_PREFIX) else "outside_network" if network is None else None
    if reason is None:
        return
    _log_event(db, request, user, action, False, ip, network, reason)
    await db.commit()
    raise HTTPException(status.HTTP_403_FORBIDDEN, REJECT_MESSAGES[reason].format(ip=ip or "không xác định"))


def _log_event(
    db: AsyncSession,
    request: Request,
    user: User,
    action: str,
    accepted: bool,
    ip: str | None,
    network: AttendanceNetwork | None,
    reason: str | None = None,
) -> None:
    db.add(
        AttendanceEvent(
            user_id=user.id,
            action=action,
            accepted=accepted,
            reason=reason,
            ip=ip,
            network_id=network.id if network else None,
            user_agent=request.headers.get("user-agent"),
        )
    )


async def _today_record(db: AsyncSession, user_id: int, day: date, lock: bool = False) -> AttendanceRecord | None:
    stmt = select(AttendanceRecord).where(AttendanceRecord.user_id == user_id, AttendanceRecord.work_date == day)
    if lock:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt)


# ---------------------------------------------------------------- Nhân viên


@router.get("/my-ip", response_model=MyIpOut, summary="IP server thấy + mạng công ty khớp (kiểm tra cấu hình)")
async def my_ip(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ip = client_ip(request)
    network = await match_network(db, ip)
    out = MyIpOut(ip=ip, network=NetworkBrief.model_validate(network) if network else None)
    if await has_permission(db, user, "attendance.manage"):
        out.x_forwarded_for = request.headers.get("x-forwarded-for")
        out.client_host = request.client.host if request.client else None
    return out


@router.get("/me/today", response_model=TodayOut, summary="Trạng thái chấm công hôm nay của tôi")
async def my_today(
    request: Request,
    user: User = Depends(require_permission("attendance.checkin")),
    db: AsyncSession = Depends(get_db),
):
    ip = client_ip(request)
    network = await match_network(db, ip)
    day = work_date_of(await _db_now(db))
    record = await _today_record(db, user.id, day)
    return TodayOut(
        work_date=day,
        is_work_day=is_work_day(day),
        ip=ip,
        network=NetworkBrief.model_validate(network) if network else None,
        shift=_shift(),
        record=await _record_out(db, record, day) if record else None,
        can_check_in=network is not None and record is None,
        can_check_out=network is not None and record is not None,
    )


@router.post(
    "/check-in",
    response_model=RecordOut,
    summary="Check-in (chỉ từ mạng công ty)",
    description="Đã check-in hôm nay thì trả bản ghi cũ, giữ giờ vào đầu tiên.",
)
async def check_in(
    request: Request,
    body: CheckBody | None = None,
    token: str = Depends(oauth2_scheme),
    user: User = Depends(require_permission("attendance.checkin")),
    db: AsyncSession = Depends(get_db),
):
    ip = client_ip(request)
    network = await match_network(db, ip)
    await _reject_if_needed(db, request, user, "check_in", token, ip, network)

    now = await _db_now(db)
    day = work_date_of(now)
    # Bấm đúp / hai tab cùng lúc: chỉ một bản ghi, giữ giờ vào đầu tiên
    await db.execute(
        pg_insert(AttendanceRecord)
        .values(
            user_id=user.id,
            work_date=day,
            check_in_at=now,
            check_in_ip=ip,
            check_in_network_id=network.id,
            late_minutes=late_minutes(day, now),
            note=body.note if body else None,
        )
        .on_conflict_do_nothing(constraint="uq_attendance_records_user_date")
    )
    _log_event(db, request, user, "check_in", True, ip, network)
    await db.commit()
    return await _record_out(db, await _today_record(db, user.id, day), day)


@router.post(
    "/check-out",
    response_model=RecordOut,
    summary="Check-out (chỉ từ mạng công ty)",
    description="Check-out nhiều lần thì giữ lần cuối. Chưa check-in hôm nay -> 409.",
)
async def check_out(
    request: Request,
    body: CheckBody | None = None,
    token: str = Depends(oauth2_scheme),
    user: User = Depends(require_permission("attendance.checkin")),
    db: AsyncSession = Depends(get_db),
):
    ip = client_ip(request)
    network = await match_network(db, ip)
    await _reject_if_needed(db, request, user, "check_out", token, ip, network)

    now = await _db_now(db)
    day = work_date_of(now)
    record = await _today_record(db, user.id, day, lock=True)
    if record is None:
        _log_event(db, request, user, "check_out", False, ip, network, "not_checked_in")
        await db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, "Hôm nay bạn chưa check-in")

    record.check_out_at, record.check_out_ip, record.check_out_network_id = now, ip, network.id
    if body and body.note:
        record.note = body.note
    recompute(record)
    _log_event(db, request, user, "check_out", True, ip, network)
    await db.commit()
    return await _record_out(db, record, day)


@router.get("/me/records", response_model=MonthOut, summary="Lịch công một tháng của tôi")
async def my_records(
    month: str = Query(pattern=MONTH_PATTERN, description="YYYY-MM"),
    user: User = Depends(require_permission("attendance.checkin")),
    db: AsyncSession = Depends(get_db),
):
    start, end = _month_range(month)
    today = work_date_of(await _db_now(db))
    records = list(
        await db.scalars(
            select(AttendanceRecord)
            .where(AttendanceRecord.user_id == user.id, AttendanceRecord.work_date.between(start, end))
            .order_by(AttendanceRecord.work_date)
        )
    )
    outs = {r.work_date: r for r in await _record_outs(db, records, today)}
    tally = _tally(records, start, end, today, work_date_of(user.created_at))
    days = []
    day = start
    while day <= end:
        days.append(DayOut(date=day, is_work_day=is_work_day(day), absent=day in tally["absent"], record=outs.get(day)))
        day += timedelta(days=1)
    tally.pop("absent")
    return MonthOut(month=month, days=days, **tally)


# ---------------------------------------------------------------- Mạng công ty


async def _ensure_cidr_free(db: AsyncSession, cidr: str, exclude_id: int | None = None) -> None:
    cond = [AttendanceNetwork.cidr == cast(cidr, CIDR)]
    if exclude_id:
        cond.append(AttendanceNetwork.id != exclude_id)
    if await db.scalar(select(exists().where(*cond))):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Mạng {cidr} đã có trong danh sách")


@router.get("/networks", response_model=list[NetworkOut], summary="Mạng công ty được phép chấm công")
async def list_networks(
    _: User = Depends(require_permission("attendance.manage")),
    db: AsyncSession = Depends(get_db),
):
    return list(await db.scalars(select(AttendanceNetwork).order_by(AttendanceNetwork.name, AttendanceNetwork.id)))


@router.post("/networks", response_model=NetworkOut, status_code=status.HTTP_201_CREATED)
async def create_network(
    body: NetworkCreate,
    user: User = Depends(require_permission("attendance.manage")),
    db: AsyncSession = Depends(get_db),
):
    cidr = normalize_cidr(body.cidr)
    await _ensure_cidr_free(db, cidr)
    network = AttendanceNetwork(**body.model_dump(exclude={"cidr"}), cidr=cidr, created_by=user.id)
    db.add(network)
    await db.commit()
    return network


@router.post(
    "/networks/current-ip",
    response_model=NetworkOut,
    status_code=status.HTTP_201_CREATED,
    summary="Thêm IP tôi đang dùng (bấm khi đang ở văn phòng)",
    description="IPv4 -> /32, IPv6 -> /64.",
)
async def create_network_from_current_ip(
    request: Request,
    body: NetworkFromCurrentIp,
    user: User = Depends(require_permission("attendance.manage")),
    db: AsyncSession = Depends(get_db),
):
    ip = client_ip(request)
    if ip is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Không xác định được IP của bạn")
    if existing := await match_network(db, ip):
        raise HTTPException(status.HTTP_409_CONFLICT, f"IP {ip} đã thuộc mạng '{existing.name}'")
    cidr = normalize_cidr(network_of_ip(ip))
    await _ensure_cidr_free(db, cidr)
    network = AttendanceNetwork(name=body.name, note=body.note, cidr=cidr, created_by=user.id)
    db.add(network)
    await db.commit()
    return network


@router.patch("/networks/{network_id}", response_model=NetworkOut)
async def update_network(
    network_id: int,
    body: NetworkUpdate,
    _: User = Depends(require_permission("attendance.manage")),
    db: AsyncSession = Depends(get_db),
):
    network = await db.get(AttendanceNetwork, network_id)
    if network is None:
        raise not_found("mạng")
    values = body.model_dump(exclude_unset=True)
    if values.get("cidr") is not None:
        values["cidr"] = normalize_cidr(values["cidr"])
        await _ensure_cidr_free(db, values["cidr"], exclude_id=network_id)
    for field, value in values.items():
        if value is not None or field == "note":
            setattr(network, field, value)
    await db.commit()
    await db.refresh(network)
    return network


@router.delete("/networks/{network_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_network(
    network_id: int,
    _: User = Depends(require_permission("attendance.manage")),
    db: AsyncSession = Depends(get_db),
):
    network = await db.get(AttendanceNetwork, network_id)
    if network is None:
        raise not_found("mạng")
    await db.delete(network)
    await db.commit()


# ---------------------------------------------------------------- Bảng công


@router.get("/records", response_model=Page[RecordOut], summary="Bảng công của mọi người")
async def list_records(
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    user_id: int | None = None,
    flag: Literal["late", "early_leave", "missing_checkout"] | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    _: User = Depends(require_permission("attendance.view")),
    db: AsyncSession = Depends(get_db),
):
    today = work_date_of(await _db_now(db))
    stmt = select(AttendanceRecord).join(User, User.id == AttendanceRecord.user_id)
    if from_:
        stmt = stmt.where(AttendanceRecord.work_date >= from_)
    if to:
        stmt = stmt.where(AttendanceRecord.work_date <= to)
    if user_id:
        stmt = stmt.where(AttendanceRecord.user_id == user_id)
    if flag == "late":
        stmt = stmt.where(AttendanceRecord.late_minutes > settings.attendance_late_grace_minutes)
    elif flag == "early_leave":
        stmt = stmt.where(
            AttendanceRecord.check_out_at.is_not(None),
            AttendanceRecord.early_leave_minutes > settings.attendance_early_grace_minutes,
        )
    elif flag == "missing_checkout":
        stmt = stmt.where(AttendanceRecord.check_out_at.is_(None), AttendanceRecord.work_date < today)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    records = list(
        await db.scalars(
            stmt.order_by(AttendanceRecord.work_date.desc(), User.full_name).limit(size).offset((page - 1) * size)
        )
    )
    items = await _record_outs(db, records, today, with_user=True)
    return {"items": items, "total": total or 0, "page": page, "size": size}


def _check_times(record: AttendanceRecord) -> None:
    if record.check_out_at is not None and record.check_out_at < record.check_in_at:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Giờ về phải sau giờ vào")


@router.post(
    "/records",
    response_model=RecordOut,
    status_code=status.HTTP_201_CREATED,
    summary="Thêm công cho ngày nhân viên quên chấm (bắt buộc lý do)",
)
async def create_record(
    body: RecordCreate,
    admin: User = Depends(require_permission("attendance.manage")),
    db: AsyncSession = Depends(get_db),
):
    today = work_date_of(await _db_now(db))
    if body.work_date > today:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Không thêm công cho ngày trong tương lai")
    target = await db.get(User, body.user_id)
    if target is None or target.deleted_at is not None:
        raise not_found("người dùng")
    if await _today_record(db, body.user_id, body.work_date):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ngày này đã có công, hãy sửa bản ghi có sẵn")
    record = AttendanceRecord(
        user_id=body.user_id,
        work_date=body.work_date,
        check_in_at=at_time(body.work_date, body.check_in_time),
        check_out_at=at_time(body.work_date, body.check_out_time) if body.check_out_time else None,
        note=body.note,
        source="admin",
        adjusted_by=admin.id,
        adjusted_reason=body.adjusted_reason,
    )
    _check_times(record)
    recompute(record)
    db.add(record)
    await db.commit()
    return await _record_out(db, record, today)


@router.patch("/records/{record_id}", response_model=RecordOut, summary="Sửa giờ vào / về (bắt buộc lý do)")
async def update_record(
    record_id: int,
    body: RecordUpdate,
    admin: User = Depends(require_permission("attendance.manage")),
    db: AsyncSession = Depends(get_db),
):
    record = await db.get(AttendanceRecord, record_id)
    if record is None:
        raise not_found("bản ghi chấm công")
    fields = body.model_fields_set
    if body.check_in_time is not None:
        record.check_in_at = at_time(record.work_date, body.check_in_time)
    if "check_out_time" in fields:
        record.check_out_at = at_time(record.work_date, body.check_out_time) if body.check_out_time else None
    if "note" in fields:
        record.note = body.note
    record.source, record.adjusted_by, record.adjusted_reason = "admin", admin.id, body.adjusted_reason
    _check_times(record)
    recompute(record)
    await db.commit()
    return await _record_out(db, record, work_date_of(await _db_now(db)))


@router.delete("/records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_record(
    record_id: int,
    _: User = Depends(require_permission("attendance.manage")),
    db: AsyncSession = Depends(get_db),
):
    record = await db.get(AttendanceRecord, record_id)
    if record is None:
        raise not_found("bản ghi chấm công")
    await db.delete(record)
    await db.commit()


# ---------------------------------------------------------------- Tổng hợp


async def _summary(db: AsyncSession, month: str) -> SummaryOut:
    start, end = _month_range(month)
    today = work_date_of(await _db_now(db))
    # Người phải chấm công: có quyền attendance.checkin qua vai trò hệ thống (đang hoạt động), hoặc có công trong tháng
    has_checkin_role = exists().where(
        UserRole.user_id == User.id,
        role_permissions.c.role_id == UserRole.role_id,
        Permission.id == role_permissions.c.permission_id,
        Permission.code == "attendance.checkin",
    )
    in_month = and_(AttendanceRecord.work_date >= start, AttendanceRecord.work_date <= end)
    has_record = exists().where(AttendanceRecord.user_id == User.id, in_month)
    users = list(
        await db.scalars(
            select(User)
            .where(
                User.deleted_at.is_(None),
                or_(and_(has_checkin_role, User.status == UserStatus.active), has_record),
            )
            .order_by(User.full_name)
        )
    )
    by_user: dict[int, list[AttendanceRecord]] = {u.id: [] for u in users}
    for r in await db.scalars(select(AttendanceRecord).where(in_month, AttendanceRecord.user_id.in_(list(by_user)))):
        by_user[r.user_id].append(r)

    rows = []
    for u in users:
        tally = _tally(by_user[u.id], start, end, today, work_date_of(u.created_at))
        tally.pop("absent")
        rows.append(SummaryRow(user=UserBrief.model_validate(u), **tally))
    work_days = sum(
        1 for i in range((end - start).days + 1) if (d := start + timedelta(days=i)) < today and is_work_day(d)
    )
    return SummaryOut(month=month, work_days=work_days, rows=rows)


@router.get("/summary", response_model=SummaryOut, summary="Tổng hợp công theo người trong tháng")
async def summary(
    month: str = Query(pattern=MONTH_PATTERN, description="YYYY-MM"),
    _: User = Depends(require_permission("attendance.view")),
    db: AsyncSession = Depends(get_db),
):
    return await _summary(db, month)


@router.get("/summary/export", summary="Tải tổng hợp tháng dạng CSV (mở bằng Excel)")
async def export_summary(
    month: str = Query(pattern=MONTH_PATTERN, description="YYYY-MM"),
    _: User = Depends(require_permission("attendance.view")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    data = await _summary(db, month)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "Tài khoản",
            "Họ tên",
            "Ngày có mặt",
            f"Vắng (/{data.work_days} ngày làm việc)",
            "Đi muộn (lần)",
            "Đi muộn (phút)",
            "Về sớm (lần)",
            "Về sớm (phút)",
            "Thiếu check-out",
            "Giờ làm",
        ]
    )
    for r in data.rows:
        writer.writerow(
            [
                r.user.username,
                r.user.full_name,
                r.present_days,
                r.absent_days,
                r.late_count,
                r.late_minutes,
                r.early_leave_count,
                r.early_leave_minutes,
                r.missing_checkout_count,
                round(r.worked_minutes / 60, 1),
            ]
        )
    # BOM để Excel nhận đúng UTF-8 (tiếng Việt có dấu)
    return Response(
        content="﻿" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="cham-cong-{month}.csv"'},
    )


@router.get("/events", response_model=Page[EventOut], summary="Log các lần bấm chấm công (kể cả bị từ chối)")
async def list_events(
    user_id: int | None = None,
    accepted: bool | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    _: User = Depends(require_permission("attendance.manage")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AttendanceEvent)
    if user_id:
        stmt = stmt.where(AttendanceEvent.user_id == user_id)
    if accepted is not None:
        stmt = stmt.where(AttendanceEvent.accepted == accepted)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    events = list(await db.scalars(stmt.order_by(AttendanceEvent.id.desc()).limit(size).offset((page - 1) * size)))
    users = await _user_briefs(db, {e.user_id for e in events})
    items = [EventOut.model_validate(e).model_copy(update={"user": users.get(e.user_id)}) for e in events]
    return {"items": items, "total": total or 0, "page": page, "size": size}
