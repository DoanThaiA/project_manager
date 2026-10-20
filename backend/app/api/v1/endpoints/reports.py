from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ProjectContext, require_permission, require_project_permission
from app.db.session import get_db
from app.models import Requirement, Sprint, User, WorkItem, WorkLog
from app.models.enums import RequirementStatus as RS
from app.models.enums import SprintStatus
from app.schemas.common import Page
from app.schemas.work import ActivityLogOut, ProjectSummary, WorkLogSummaryRow
from app.services.activity import activity_query, fetch_activity

router = APIRouter()  # /projects/{project_id}/...
system_router = APIRouter()  # /activity-logs (toàn hệ thống)


@router.get("/reports/summary", response_model=ProjectSummary, summary="Tổng quan dự án")
async def project_summary(
    ctx: ProjectContext = Depends(require_project_permission("report.view")),
    db: AsyncSession = Depends(get_db),
):
    pid = ctx.project.id
    req_rows = await db.execute(
        select(Requirement.status, func.count())
        .where(Requirement.project_id == pid, Requirement.deleted_at.is_(None))
        .group_by(Requirement.status)
    )
    overdue = await db.scalar(
        select(func.count()).where(
            Requirement.project_id == pid,
            Requirement.deleted_at.is_(None),
            Requirement.due_date < func.current_date(),
            Requirement.status.not_in([RS.done, RS.closed, RS.cancelled, RS.rejected]),
        )
    )
    item_rows = await db.execute(
        select(WorkItem.status, func.count())
        .where(WorkItem.project_id == pid, WorkItem.deleted_at.is_(None))
        .group_by(WorkItem.status)
    )
    total_hours = await db.scalar(select(func.coalesce(func.sum(WorkLog.hours), 0)).where(WorkLog.project_id == pid))

    active = await db.scalar(select(Sprint).where(Sprint.project_id == pid, Sprint.status == SprintStatus.active))
    active_sprint = None
    if active:
        points = (
            await db.execute(
                select(
                    func.coalesce(func.sum(WorkItem.story_points), 0),
                    func.coalesce(func.sum(WorkItem.story_points).filter(WorkItem.status == "done"), 0),
                    func.coalesce(func.sum(WorkItem.remaining_hours), 0),
                ).where(WorkItem.sprint_id == active.id, WorkItem.deleted_at.is_(None))
            )
        ).one()
        active_sprint = {
            "id": active.id,
            "name": active.name,
            "goal": active.goal,
            "start_date": active.start_date,
            "end_date": active.end_date,
            "days_left": max((active.end_date - date.today()).days, 0),
            "planned_points": points[0],
            "completed_points": points[1],
            "remaining_hours": points[2],
        }

    return ProjectSummary(
        requirements_by_status={str(s): n for s, n in req_rows.all()},
        requirements_overdue=overdue or 0,
        work_items_by_status={str(s): n for s, n in item_rows.all()},
        total_logged_hours=total_hours,
        budget_hours=ctx.project.budget_hours,
        active_sprint=active_sprint,
    )


@router.get("/reports/work-logs", response_model=list[WorkLogSummaryRow], summary="Tổng hợp giờ làm")
async def work_log_summary(
    group_by: Literal["user", "date", "activity_type", "work_item", "sprint"] = "user",
    date_from: date | None = None,
    date_to: date | None = None,
    ctx: ProjectContext = Depends(require_project_permission("report.view")),
    db: AsyncSession = Depends(get_db),
):
    if group_by == "user":
        key, label = WorkLog.user_id, User.full_name
        stmt = select(key, label).join(User, User.id == WorkLog.user_id)
    elif group_by == "date":
        key = label = WorkLog.log_date
        stmt = select(key, label)
    elif group_by == "activity_type":
        key = label = WorkLog.activity_type
        stmt = select(key, label)
    elif group_by == "work_item":
        key, label = WorkLog.work_item_id, WorkItem.code
        stmt = select(key, label).outerjoin(WorkItem, WorkItem.id == WorkLog.work_item_id)
    else:
        key, label = WorkLog.sprint_id, Sprint.name
        stmt = select(key, label).outerjoin(Sprint, Sprint.id == WorkLog.sprint_id)

    stmt = (
        stmt.add_columns(
            func.sum(WorkLog.hours),
            func.coalesce(func.sum(WorkLog.hours).filter(WorkLog.is_billable), 0),
        )
        .where(WorkLog.project_id == ctx.project.id)
        .group_by(key, label)
        .order_by(key)
    )
    if date_from:
        stmt = stmt.where(WorkLog.log_date >= date_from)
    if date_to:
        stmt = stmt.where(WorkLog.log_date <= date_to)

    return [
        WorkLogSummaryRow(
            key="none" if k is None else str(k),
            label=None if lb is None else str(lb),
            total_hours=total,
            billable_hours=billable,
        )
        for k, lb, total, billable in (await db.execute(stmt)).all()
    ]


@router.get("/activity-logs", response_model=Page[ActivityLogOut], summary="Nhật ký hoạt động của dự án")
async def project_activity_logs(
    entity_type: str | None = None,
    entity_id: int | None = None,
    actor_id: int | None = None,
    action: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    ctx: ProjectContext = Depends(require_project_permission("activity_log.view")),
    db: AsyncSession = Depends(get_db),
):
    stmt = activity_query(
        project_id=ctx.project.id,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        action=action,
        date_from=date_from,
        date_to=date_to,
    )
    return await fetch_activity(db, stmt, page, size)


@system_router.get("", response_model=Page[ActivityLogOut], summary="Nhật ký hoạt động toàn hệ thống")
async def system_activity_logs(
    project_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    actor_id: int | None = None,
    action: str | None = Query(default=None, description="vd: login, login_failed, create, update, status_change"),
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    _: User = Depends(require_permission("activity_log.view")),
    db: AsyncSession = Depends(get_db),
):
    stmt = activity_query(
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        action=action,
        date_from=date_from,
        date_to=date_to,
    )
    return await fetch_activity(db, stmt, page, size)
