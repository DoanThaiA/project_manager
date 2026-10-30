"""Bộ tools chỉ đọc cho ban lãnh đạo: tiến độ, hiệu suất, yêu cầu, công việc, nhật ký.

Mỗi tool gọi đúng một endpoint REST có sẵn; quyền do API kiểm tra theo user sở hữu token.
"""

import asyncio
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from app.mcp_server.client import client

INSTRUCTIONS = """Hệ thống quản lý dự án phần mềm (Scrum/Agile). Chỉ đọc, không sửa dữ liệu.
- Mã dự án là số id (lấy từ list_projects). Mã yêu cầu hiển thị dạng ERP-REQ-0012, mã công việc dạng ERP-12.
- Ngày theo định dạng YYYY-MM-DD, múi giờ Asia/Ho_Chi_Minh.
- Số liệu giờ log và story point chỉ là chỉ báo tiến độ; không dùng riêng lẻ để đánh giá cá nhân.
- Danh sách trả về có phân trang: tham số limit tối đa 50, kiểm tra total để biết còn dữ liệu hay không."""

mcp = MCPServer("Project Manager", instructions=INSTRUCTIONS)

MAX_LIMIT = 50


def _limit(limit: int) -> int:
    return min(max(limit, 1), MAX_LIMIT)


async def _page(path: str, params: dict[str, Any], limit: int) -> dict[str, Any]:
    data = await client.get(path, {**params, "size": _limit(limit)})
    return {"total": data["total"], "items": data["items"]}


async def _active_sprint_id(project_id: int) -> int:
    sprints = await client.get(f"/projects/{project_id}/sprints", {"status": "active"})
    if not sprints:
        raise ToolError("Dự án này không có sprint đang chạy; hãy truyền sprint_id cụ thể (xem list_sprints)")
    return sprints[0]["id"]


@mcp.tool()
async def list_projects(status: str | None = None, q: str | None = None, limit: int = 20) -> dict[str, Any]:
    """Danh sách dự án. status: planning, active, on_hold, completed, cancelled. q: tìm theo mã hoặc tên."""
    return await _page("/projects", {"status": status, "q": q}, limit)


@mcp.tool()
async def project_overview(project_id: int) -> dict[str, Any]:
    """Tổng quan dự án: yêu cầu theo trạng thái (và quá hạn), công việc, tổng giờ log, ngân sách, sprint đang chạy."""
    return await client.get(f"/projects/{project_id}/reports/summary")


@mcp.tool()
async def list_sprints(project_id: int, status: str | None = None) -> list[dict[str, Any]]:
    """Danh sách sprint của dự án. status: planned, active, completed, cancelled."""
    return await client.get(f"/projects/{project_id}/sprints", {"status": status})


@mcp.tool()
async def sprint_progress(project_id: int, sprint_id: int | None = None) -> dict[str, Any]:
    """Tiến độ sprint (story point kế hoạch/hoàn thành, giờ log). Bỏ trống sprint_id = sprint đang chạy."""
    sid = sprint_id or await _active_sprint_id(project_id)
    return await client.get(f"/projects/{project_id}/sprints/{sid}/progress")


@mcp.tool()
async def list_requirements(
    project_id: int,
    q: str | None = None,
    status: list[str] | None = None,
    priority: list[str] | None = None,
    overdue: bool | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Yêu cầu khách hàng của dự án. overdue=true: chỉ yêu cầu quá hạn. priority: lowest…critical."""
    params = {"q": q, "status": status, "priority": priority, "overdue": overdue}
    return await _page(f"/projects/{project_id}/requirements", params, limit)


@mcp.tool()
async def requirement_detail(project_id: int, requirement_id: int) -> dict[str, Any]:
    """Chi tiết yêu cầu: nội dung, tiêu chí nghiệm thu, lịch sử trạng thái, 30 bình luận gần nhất (gồm nội bộ)."""
    base = f"/projects/{project_id}/requirements/{requirement_id}"
    detail, history, comments = await asyncio.gather(
        client.get(base),
        client.get(f"{base}/history"),
        client.get(f"{base}/comments"),
    )
    return {"detail": detail, "history": history, "comments": comments[-30:]}


@mcp.tool()
async def list_work_items(
    project_id: int,
    sprint_id: int | None = None,
    status: list[str] | None = None,
    assignee_id: int | None = None,
    backlog: bool | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Công việc của dự án. backlog=true: chỉ Product Backlog. status: backlog, todo, in_progress, in_review, done…"""
    params = {"sprint_id": sprint_id, "status": status, "assignee_id": assignee_id, "backlog": backlog}
    return await _page(f"/projects/{project_id}/work-items", params, limit)


@mcp.tool()
async def team_performance(
    project_id: int,
    group_by: Literal["user", "date", "activity_type", "work_item", "sprint"] = "user",
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    """Tổng hợp giờ log theo nhóm: user, sprint, activity_type, date, work_item. Lọc theo khoảng ngày."""
    params = {"group_by": group_by, "date_from": date_from, "date_to": date_to}
    return await client.get(f"/projects/{project_id}/reports/work-logs", params)


@mcp.tool()
async def project_members(project_id: int) -> list[dict[str, Any]]:
    """Thành viên dự án và vai trò trong dự án."""
    return await client.get(f"/projects/{project_id}/members")


@mcp.tool()
async def activity_timeline(
    project_id: int | None = None,
    entity_type: str | None = None,
    actor_id: int | None = None,
    action: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    """Nhật ký thay đổi: ai đổi gì, lúc nào. Lọc theo dự án, entity_type, người, action, khoảng ngày."""
    params = {
        "project_id": project_id,
        "entity_type": entity_type,
        "actor_id": actor_id,
        "action": action,
        "date_from": date_from,
        "date_to": date_to,
    }
    return await _page("/activity-logs", params, limit)


@mcp.tool()
async def list_customers(q: str | None = None, limit: int = 20) -> dict[str, Any]:
    """Khách hàng. q: tìm theo mã, tên hoặc email."""
    return await _page("/customers", {"q": q}, limit)
