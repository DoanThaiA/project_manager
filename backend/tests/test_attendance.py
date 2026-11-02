from datetime import date, datetime, time
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models import ActivityLog
from app.services.attendance import VN_TZ, early_leave_minutes, flags, late_minutes, work_date_of, worked_minutes

OFFICE_IP = "113.161.10.20"
OFFICE_V6 = "2402:800:1234::/56"
HOME_IP = "14.231.5.6"
SHIFT_FIELDS = ("name", "late_grace_minutes", "early_grace_minutes", "days")


def _from(ip: str) -> dict[str, str]:
    """Request đi qua nginx: X-Forwarded-For = IP client (ASGI client 127.0.0.1 là proxy tin cậy)."""
    return {"X-Forwarded-For": ip}


def _vn(day: date, hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, ss, tzinfo=VN_TZ)


# Lịch theo ngày của 2 ca có sẵn sau migration 0014
WEEKDAY = SimpleNamespace(start_time=time(8), end_time=time(17, 30), break_start=time(12), break_end=time(13, 30))
SATURDAY = SimpleNamespace(start_time=time(8), end_time=time(12), break_start=None, break_end=None)
MORNING = SATURDAY  # Ca sáng T2 - T6: cùng giờ với T7 của ca Hành chính
GRACE = SimpleNamespace(late_grace_minutes=5, early_grace_minutes=0)


@pytest.fixture(scope="module")
async def office(client, login):
    headers = await login("admin")
    for name, cidr in (("VP Hà Nội", OFFICE_IP), ("VP Hà Nội IPv6", OFFICE_V6)):
        resp = await client.post("/attendance/networks", json={"name": name, "cidr": cidr}, headers=headers)
        assert resp.status_code in (201, 409), resp.text


async def _user_id(client, login, username: str) -> int:
    return (await client.get("/auth/me", headers=await login(username))).json()["id"]


# ---------------------------------------------------------------- Tính toán


def test_minutes_follow_day_schedule():
    day = date(2026, 11, 2)
    assert late_minutes(day, _vn(day, 7, 50), WEEKDAY) == 0
    assert late_minutes(day, _vn(day, 8, 5, 59), WEEKDAY) == 5
    assert late_minutes(day, _vn(day, 8, 6), WEEKDAY) == 6
    assert worked_minutes(day, _vn(day, 8, 0), _vn(day, 17, 30), WEEKDAY) == 480  # 9h30 - 1h30 nghỉ trưa
    assert worked_minutes(day, _vn(day, 12, 30), _vn(day, 17, 30), WEEKDAY) == 240  # vào giữa giờ nghỉ
    assert worked_minutes(day, _vn(day, 8, 0), _vn(day, 11, 0), WEEKDAY) == 180  # không chạm giờ nghỉ
    # Ngày nghỉ (không có lịch): không tính muộn / về sớm, giờ làm = ra - vào
    assert late_minutes(day, _vn(day, 9, 0), None) == 0
    assert early_leave_minutes(day, _vn(day, 10, 0), None) == 0
    assert worked_minutes(day, _vn(day, 9, 0), _vn(day, 10, 0), None) == 60
    # Ca sáng: không có nghỉ trưa, về trước 12:00 là về sớm
    assert worked_minutes(day, _vn(day, 8, 0), _vn(day, 12, 0), MORNING) == 240
    assert early_leave_minutes(day, _vn(day, 11, 30), MORNING) == 30
    assert early_leave_minutes(day, _vn(day, 12, 30), MORNING) == 0


def test_work_date_uses_vietnam_time():
    assert work_date_of(datetime.fromisoformat("2026-11-02T16:59:00+00:00")) == date(2026, 11, 2)  # 23:59
    assert work_date_of(datetime.fromisoformat("2026-11-02T17:01:00+00:00")) == date(2026, 11, 3)  # 00:01


def test_flags_respect_grace_minutes():
    class R:
        work_date = date(2026, 11, 2)
        check_out_at = None
        early_leave_minutes = 0

    record = R()
    record.late_minutes = 5
    today = date(2026, 11, 2)
    assert flags(record, today, GRACE) == {"is_late": False, "is_early_leave": False, "missing_checkout": False}
    record.late_minutes = 6
    assert flags(record, date(2026, 11, 3), GRACE) == {
        "is_late": True,
        "is_early_leave": False,
        "missing_checkout": True,
    }


# ---------------------------------------------------------------- IP


async def test_client_ip_ignores_spoofed_forwarded_for(client, login, office):
    headers = await login("dev.cuong")

    async def seen(xff: str) -> dict:
        return (await client.get("/attendance/my-ip", headers={**headers, "X-Forwarded-For": xff})).json()

    # Client tự gửi IP văn phòng ở đầu chuỗi: bị bỏ qua, lấy IP thật do nginx nối vào
    spoofed = await seen(f"{OFFICE_IP}, {HOME_IP}")
    assert spoofed["ip"] == HOME_IP and spoofed["network"] is None
    # Hop docker (Next.js) bên phải là proxy tin cậy
    assert (await seen(f"{OFFICE_IP}, 172.18.0.5"))["network"]["name"] == "VP Hà Nội"
    assert (await seen(f"rác, {HOME_IP}"))["ip"] == HOME_IP
    assert (await seen(f"::ffff:{OFFICE_IP}"))["ip"] == OFFICE_IP
    assert (await seen("2402:800:1234:5::abcd"))["network"]["name"] == "VP Hà Nội IPv6"
    # Người không có quyền manage không thấy header gốc
    assert spoofed["x_forwarded_for"] is None


# ---------------------------------------------------------------- Chấm công


async def test_check_in_and_out_from_office(client, login, office):
    headers = await login("dev.cuong")

    today = await client.get("/attendance/me/today", headers={**headers, **_from(OFFICE_IP)})
    assert today.status_code == 200, today.text
    assert today.json()["shift"]["name"] == "Hành chính"
    assert today.json()["schedule"] is None or today.json()["schedule"]["start_time"] == "08:00:00"
    assert today.json()["network"]["name"] == "VP Hà Nội"

    first = await client.post("/attendance/check-in", headers={**headers, **_from(OFFICE_IP)})
    assert first.status_code == 200, first.text
    assert first.json()["check_in_ip"] == OFFICE_IP
    assert first.json()["check_in_network"]["name"] == "VP Hà Nội"

    # Bấm lại: giữ giờ vào đầu tiên
    again = await client.post("/attendance/check-in", headers={**headers, **_from(OFFICE_IP)})
    assert again.json()["id"] == first.json()["id"]
    assert again.json()["check_in_at"] == first.json()["check_in_at"]

    out1 = await client.post("/attendance/check-out", headers={**headers, **_from(OFFICE_IP)})
    assert out1.status_code == 200, out1.text
    out2 = await client.post("/attendance/check-out", json={"note": "về muộn"}, headers={**headers, **_from(OFFICE_IP)})
    assert out2.json()["check_out_at"] >= out1.json()["check_out_at"]  # giữ lần cuối
    assert out2.json()["worked_minutes"] is not None
    assert out2.json()["note"] == "về muộn"

    state = (await client.get("/attendance/me/today", headers={**headers, **_from(OFFICE_IP)})).json()
    assert state["can_check_in"] is False and state["can_check_out"] is True

    month = state["work_date"][:7]
    cal = (await client.get("/attendance/me/records", params={"month": month}, headers=headers)).json()
    assert cal["present_days"] == 1
    assert next(d for d in cal["days"] if d["date"] == state["work_date"])["record"]["id"] == first.json()["id"]


async def test_rejected_outside_office_and_logged(client, login, office):
    headers = await login("qa.dung")
    resp = await client.post("/attendance/check-in", headers={**headers, **_from(HOME_IP)})
    assert resp.status_code == 403
    assert HOME_IP in resp.json()["detail"]

    state = (await client.get("/attendance/me/today", headers={**headers, **_from(HOME_IP)})).json()
    assert state["record"] is None and state["can_check_in"] is False

    uid = await _user_id(client, login, "qa.dung")
    events = (
        await client.get("/attendance/events", params={"user_id": uid, "accepted": False}, headers=await login("admin"))
    ).json()
    assert events["items"][0]["reason"] == "outside_network"
    assert events["items"][0]["ip"] == HOME_IP


async def test_check_out_requires_check_in(client, login, office):
    resp = await client.post("/attendance/check-out", headers={**await login("sm.binh"), **_from(OFFICE_IP)})
    assert resp.status_code == 409


async def test_api_token_cannot_check_in(client, login, office):
    created = await client.post(
        "/me/api-tokens", json={"name": "script", "expires_days": 1}, headers=await login("sm.binh")
    )
    pat = {"Authorization": f"Bearer {created.json()['token']}"}
    resp = await client.post("/attendance/check-in", headers={**pat, **_from(OFFICE_IP)})
    assert resp.status_code == 403
    assert "PAT" in resp.json()["detail"]


async def test_customer_cannot_check_in(client, login, office):
    resp = await client.post("/attendance/check-in", headers={**await login("kh.abc"), **_from(OFFICE_IP)})
    assert resp.status_code == 403
    staff = await client.get("/attendance/records", headers=await login("dev.cuong"))
    assert staff.status_code == 403  # nhân viên không xem bảng công người khác


# ---------------------------------------------------------------- Quản lý


async def test_network_validation(client, login, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "attendance_allow_private_networks", False)
    headers = await login("admin")
    for cidr in ("0.0.0.0/0", "1.0.0.0/8", "192.168.1.0/24", "2402:800::/32", "không phải ip"):
        resp = await client.post("/attendance/networks", json={"name": "x", "cidr": cidr}, headers=headers)
        assert resp.status_code == 422, cidr

    ok = await client.post("/attendance/networks", json={"name": "Chi nhánh", "cidr": "42.118.5.9/29"}, headers=headers)
    assert ok.status_code == 201, ok.text
    assert ok.json()["cidr"] == "42.118.5.8/29"
    dup = await client.post("/attendance/networks", json={"name": "y", "cidr": "42.118.5.8/29"}, headers=headers)
    assert dup.status_code == 409

    off = await client.patch(f"/attendance/networks/{ok.json()['id']}", json={"is_active": False}, headers=headers)
    assert off.json()["is_active"] is False
    seen = await client.get("/attendance/my-ip", headers={**headers, **_from("42.118.5.10")})
    assert seen.json()["network"] is None  # mạng đã tắt
    assert seen.json()["x_forwarded_for"] == "42.118.5.10"

    from_ip = await client.post(
        "/attendance/networks/current-ip", json={"name": "Wi-Fi tầng 3"}, headers={**headers, **_from("42.118.7.33")}
    )
    assert from_ip.status_code == 201, from_ip.text
    assert from_ip.json()["cidr"] == "42.118.7.33/32"
    assert (await client.delete(f"/attendance/networks/{ok.json()['id']}", headers=headers)).status_code == 204


async def test_admin_adds_and_fixes_record(client, login):
    headers = await login("admin")
    uid = await _user_id(client, login, "qa.dung")
    body = {"user_id": uid, "work_date": "2026-10-05", "check_in_time": "08:20", "check_out_time": "17:00"}

    assert (await client.post("/attendance/records", json=body, headers=headers)).status_code == 422  # thiếu lý do
    created = await client.post(
        "/attendance/records", json={**body, "adjusted_reason": "Quên chấm công"}, headers=headers
    )
    assert created.status_code == 201, created.text
    rec = created.json()
    assert (rec["late_minutes"], rec["early_leave_minutes"], rec["worked_minutes"]) == (20, 30, 430)
    assert rec["credit"] == 1  # thứ 2: đủ vào + về -> 1 công
    assert rec["is_late"] and rec["is_early_leave"] and rec["source"] == "admin"

    dup = await client.post("/attendance/records", json={**body, "adjusted_reason": "lần 2"}, headers=headers)
    assert dup.status_code == 409

    bad = await client.patch(
        f"/attendance/records/{rec['id']}",
        json={"check_out_time": "07:00", "adjusted_reason": "sai"},
        headers=headers,
    )
    assert bad.status_code == 422
    fixed = await client.patch(
        f"/attendance/records/{rec['id']}",
        json={"check_out_time": "17:45", "adjusted_reason": "Về muộn, quên check-out"},
        headers=headers,
    )
    assert fixed.status_code == 200, fixed.text
    # 08:20 -> 17:45 trừ 1h30 nghỉ trưa
    assert (fixed.json()["early_leave_minutes"], fixed.json()["worked_minutes"]) == (0, 475)

    # Admin thêm / sửa công -> ghi nhật ký hệ thống
    async with AsyncSessionLocal() as db:
        actions = list(
            await db.scalars(
                select(ActivityLog.action).where(
                    ActivityLog.entity_type == "attendance_records", ActivityLog.entity_id == rec["id"]
                )
            )
        )
    assert "create" in actions and "update" in actions

    late = await client.get(
        "/attendance/records", params={"from": "2026-10-01", "to": "2026-10-31", "flag": "late"}, headers=headers
    )
    assert rec["id"] in [r["id"] for r in late.json()["items"]]
    assert late.json()["items"][0]["user"]["username"]


async def test_monthly_summary_and_export(client, login):
    headers = await login("admin")
    data = (await client.get("/attendance/summary", params={"month": "2026-10"}, headers=headers)).json()
    rows = {r["user"]["username"]: r for r in data["rows"]}
    assert "kh.abc" not in rows  # khách hàng không chấm công
    assert {"dev.cuong", "sm.binh"} <= rows.keys()  # vai trò STAFF
    assert rows["qa.dung"]["present_days"] >= 1 and rows["qa.dung"]["late_count"] >= 1

    assert (await client.get("/attendance/summary", params={"month": "2026-13"}, headers=headers)).status_code == 422

    csv_resp = await client.get("/attendance/summary/export", params={"month": "2026-10"}, headers=headers)
    assert csv_resp.status_code == 200
    assert csv_resp.headers["content-type"].startswith("text/csv")
    assert csv_resp.text.startswith("﻿Tài khoản")
    assert "qa.dung" in csv_resp.text


async def test_shifts_and_assignment(client, login, office):
    headers = await login("admin")
    shifts = {s["name"]: s for s in (await client.get("/attendance/shifts", headers=headers)).json()}
    office_hours, morning = shifts["Hành chính"], shifts["Ca sáng"]
    assert office_hours["is_default"] and not morning["is_default"]
    days = {d["weekday"]: d for d in office_hours["days"]}
    assert set(days) == {1, 2, 3, 4, 5, 6}  # CN nghỉ
    assert (days[1]["end_time"], days[1]["break_start"], days[1]["credit"]) == ("17:30:00", "12:00:00", 1)
    assert (days[6]["start_time"], days[6]["end_time"], days[6]["break_start"], days[6]["credit"]) == (
        "08:00:00",
        "12:00:00",
        None,
        0.5,
    )
    assert [d["weekday"] for d in morning["days"]] == [1, 2, 3, 4, 5]  # ca sáng nghỉ T7
    assert {d["credit"] for d in morning["days"]} == {1}  # ca sáng ngày thường: 1 công

    def day(weekday: int, start: str, end: str, **extra) -> dict:
        return {"weekday": weekday, "start_time": start, "end_time": end, **extra}

    for bad_days in (
        [day(1, "17:00", "08:00")],
        [day(1, "08:00", "12:00", break_start="12:30", break_end="13:00")],
        [day(1, "08:00", "12:00"), day(1, "13:00", "17:00")],  # trùng thứ
        [day(1, "08:00", "12:00", credit=0)],
        [],
    ):
        resp = await client.post("/attendance/shifts", json={"name": "Sai", "days": bad_days}, headers=headers)
        assert resp.status_code == 422, bad_days

    # Thứ 7 ca Hành chính: 08:00 - 12:00, 0,5 công; CN: ngoài ngày làm việc, 0 công
    cuong = await _user_id(client, login, "dev.cuong")
    base = {"user_id": cuong, "adjusted_reason": "Quên chấm"}
    sat = await client.post(
        "/attendance/records",
        json={**base, "work_date": "2026-10-10", "check_in_time": "08:05", "check_out_time": "12:00"},
        headers=headers,
    )
    assert sat.status_code == 201, sat.text
    r = sat.json()
    assert (r["late_minutes"], r["is_late"], r["early_leave_minutes"], r["worked_minutes"], r["credit"]) == (
        5,
        False,
        0,
        235,
        0.5,
    )
    sun = await client.post(
        "/attendance/records",
        json={**base, "work_date": "2026-10-11", "check_in_time": "09:00", "check_out_time": "11:00"},
        headers=headers,
    )
    assert (sun.json()["late_minutes"], sun.json()["worked_minutes"], sun.json()["credit"]) == (0, 120, 0)
    no_out = await client.post(
        "/attendance/records", json={**base, "work_date": "2026-10-12", "check_in_time": "08:00"}, headers=headers
    )
    assert no_out.json()["credit"] == 0  # thiếu check-out: chưa tính công

    # Gán ca sáng cho sm.binh: ca hôm nay + công thêm tay đều tính theo ca sáng
    uid = await _user_id(client, login, "sm.binh")
    assigned = await client.put(f"/attendance/users/{uid}/shift", json={"shift_id": morning["id"]}, headers=headers)
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["shift"]["name"] == "Ca sáng"
    today = (await client.get("/attendance/me/today", headers=await login("sm.binh"))).json()
    assert today["shift"]["name"] == "Ca sáng"
    assert today["schedule"] is None or today["schedule"]["end_time"] == "12:00:00"

    rec = await client.post(
        "/attendance/records",
        json={
            "user_id": uid,
            "work_date": "2026-10-06",
            "check_in_time": "08:00",
            "check_out_time": "11:30",
            "adjusted_reason": "Quên chấm",
        },
        headers=headers,
    )
    assert rec.status_code == 201, rec.text
    assert rec.json()["shift"]["name"] == "Ca sáng"
    assert (rec.json()["early_leave_minutes"], rec.json()["worked_minutes"], rec.json()["credit"]) == (30, 210, 1)
    assert rec.json()["is_early_leave"]

    rows = {
        r["user"]["username"]: r
        for r in (await client.get("/attendance/summary", params={"month": "2026-10"}, headers=headers)).json()["rows"]
    }
    assert rows["sm.binh"]["shift"]["name"] == "Ca sáng"
    assert rows["sm.binh"]["assigned_shift_id"] == morning["id"]
    assert rows["sm.binh"]["credit"] == 1
    assert rows["dev.cuong"]["assigned_shift_id"] is None and rows["dev.cuong"]["shift"]["name"] == "Hành chính"
    assert rows["dev.cuong"]["credit"] == 0.5  # T7 0,5 + CN 0 + thiếu check-out 0
    listed = {s["name"]: s for s in (await client.get("/attendance/shifts", headers=headers)).json()}
    assert listed["Ca sáng"]["user_count"] == 1

    # Ca đã có công / ca mặc định không xoá được; phải luôn có một ca mặc định
    assert (await client.delete(f"/attendance/shifts/{morning['id']}", headers=headers)).status_code == 409
    assert (await client.delete(f"/attendance/shifts/{office_hours['id']}", headers=headers)).status_code == 409
    keep = {k: office_hours[k] for k in SHIFT_FIELDS}
    resp = await client.put(
        f"/attendance/shifts/{office_hours['id']}", json={**keep, "is_default": False}, headers=headers
    )
    assert resp.status_code == 422

    # Sửa lịch tại chỗ: bỏ T7, thêm CN, đổi giờ T2
    created = await client.post(
        "/attendance/shifts",
        json={"name": "Ca chiều", "days": [day(6, "13:30", "17:30", credit=0.5), day(1, "13:30", "17:30")]},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert [d["weekday"] for d in created.json()["days"]] == [1, 6]
    edited = await client.put(
        f"/attendance/shifts/{created.json()['id']}",
        json={"name": "Ca chiều", "days": [day(1, "13:00", "17:00"), day(7, "13:00", "17:00", credit=0.5)]},
        headers=headers,
    )
    assert edited.status_code == 200, edited.text
    assert [(d["weekday"], d["start_time"]) for d in edited.json()["days"]] == [(1, "13:00:00"), (7, "13:00:00")]
    assert (await client.delete(f"/attendance/shifts/{created.json()['id']}", headers=headers)).status_code == 204

    back = await client.put(f"/attendance/users/{uid}/shift", json={"shift_id": None}, headers=headers)
    assert back.json()["shift"]["name"] == "Hành chính"
    staff = await client.put(
        f"/attendance/users/{uid}/shift", json={"shift_id": None}, headers=await login("dev.cuong")
    )
    assert staff.status_code == 403
