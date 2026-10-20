from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ProjectContext, get_current_user, has_permission, require_project_permission
from app.api.v1.endpoints.requirements import get_requirement
from app.api.v1.endpoints.work_items import get_work_item
from app.db.session import get_db
from app.models import Sprint, User, WorkLog
from app.models.enums import SprintStatus, WorkActivityType
from app.schemas.common import Page
from app.schemas.work import WorkLogCreate, WorkLogOut, WorkLogUpdate
from app.services.common import not_found, paginate

router = APIRouter()
me_router = APIRouter()

MAX_HOURS_PER_DAY = 24


async def _check_daily_limit(
    db: AsyncSession, user_id: int, log_date: date, hours, exclude_id: int | None = None
) -> None:
    stmt = select(func.coalesce(func.sum(WorkLog.hours), 0)).where(
        WorkLog.user_id == user_id, WorkLog.log_date == log_date
    )
    if exclude_id:
        stmt = stmt.where(WorkLog.id != exclude_id)
    logged = await db.scalar(stmt)
    if logged + hours > MAX_HOURS_PER_DAY:
        raise HTTPException(
            status_code=422,
            detail=f"Tổng giờ ngày {log_date} vượt {MAX_HOURS_PER_DAY}h (đã log {logged}h)",
        )


def _filter(
    stmt,
    *,
    user_id: int | None,
    date_from: date | None,
    date_to: date | None,
    work_item_id: int | None = None,
    requirement_id: int | None = None,
    sprint_id: int | None = None,
    activity_type: WorkActivityType | None = None,
):
    if user_id is not None:
        stmt = stmt.where(WorkLog.user_id == user_id)
    if date_from:
        stmt = stmt.where(WorkLog.log_date >= date_from)
    if date_to:
        stmt = stmt.where(WorkLog.log_date <= date_to)
    if work_item_id is not None:
        stmt = stmt.where(WorkLog.work_item_id == work_item_id)
    if requirement_id is not None:
        stmt = stmt.where(WorkLog.requirement_id == requirement_id)
    if sprint_id is not None:
        stmt = stmt.where(WorkLog.sprint_id == sprint_id)
    if activity_type:
        stmt = stmt.where(WorkLog.activity_type == activity_type)
    return stmt.order_by(WorkLog.log_date.desc(), WorkLog.id.desc())


@router.get("", response_model=Page[WorkLogOut])
async def list_work_logs(
    user_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    work_item_id: int | None = None,
    requirement_id: int | None = None,
    sprint_id: int | None = None,
    activity_type: WorkActivityType | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=500),
    ctx: ProjectContext = Depends(require_project_permission("work_log.view")),
    db: AsyncSession = Depends(get_db),
):
    stmt = _filter(
        select(WorkLog).where(WorkLog.project_id == ctx.project.id),
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        work_item_id=work_item_id,
        requirement_id=requirement_id,
        sprint_id=sprint_id,
        activity_type=activity_type,
    )
    return await paginate(db, stmt, page, size)


@router.post("", response_model=WorkLogOut, status_code=status.HTTP_201_CREATED, summary="Ghi log công việc")
async def create_work_log(
    body: WorkLogCreate,
    ctx: ProjectContext = Depends(require_project_permission("work_log.create")),
    db: AsyncSession = Depends(get_db),
):
    pid = ctx.project.id
    if body.log_date > date.today():
        raise HTTPException(status_code=422, detail="Không thể log cho ngày trong tương lai")
    await _check_daily_limit(db, ctx.user.id, body.log_date, body.hours)

    sprint_id = None
    item = None
    if body.work_item_id:
        item = await get_work_item(db, pid, body.work_item_id)
        sprint_id = item.sprint_id
    if body.requirement_id:
        await get_requirement(db, pid, body.requirement_id)
    if sprint_id is None:  # log chung -> gắn vào sprint chứa ngày log
        sprint_id = await db.scalar(
            select(Sprint.id).where(
                Sprint.project_id == pid,
                Sprint.status.in_([SprintStatus.active, SprintStatus.completed]),
                Sprint.start_date <= body.log_date,
                Sprint.end_date >= body.log_date,
            )
        )

    log = WorkLog(
        project_id=pid,
        user_id=ctx.user.id,
        sprint_id=sprint_id,
        **body.model_dump(exclude={"remaining_hours"}),
    )
    db.add(log)

    # Cập nhật giờ còn lại của công việc
    if item is not None:
        if body.remaining_hours is not None:
            item.remaining_hours = body.remaining_hours
        elif item.remaining_hours is not None:
            item.remaining_hours = max(item.remaining_hours - body.hours, 0)
    await db.commit()
    return log


async def _get_own_or_manage(db: AsyncSession, ctx: ProjectContext, log_id: int) -> WorkLog:
    log = await db.get(WorkLog, log_id)
    if log is None or log.project_id != ctx.project.id:
        raise not_found("log công việc")
    if log.user_id != ctx.user.id and not await has_permission(db, ctx.user, "work_log.manage", ctx.project.id):
        raise HTTPException(status_code=403, detail="Chỉ sửa / xoá được log của mình")
    return log


@router.patch("/{log_id}", response_model=WorkLogOut)
async def update_work_log(
    log_id: int,
    body: WorkLogUpdate,
    ctx: ProjectContext = Depends(require_project_permission("work_log.create")),
    db: AsyncSession = Depends(get_db),
):
    log = await _get_own_or_manage(db, ctx, log_id)
    values = body.model_dump(exclude_unset=True)
    if values.get("log_date") and values["log_date"] > date.today():
        raise HTTPException(status_code=422, detail="Không thể log cho ngày trong tương lai")
    if "hours" in values or "log_date" in values:
        await _check_daily_limit(
            db, log.user_id, values.get("log_date", log.log_date), values.get("hours", log.hours), exclude_id=log.id
        )
    for field, value in values.items():
        setattr(log, field, value)
    await db.commit()
    return log


@router.delete("/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_work_log(
    log_id: int,
    ctx: ProjectContext = Depends(require_project_permission("work_log.create")),
    db: AsyncSession = Depends(get_db),
):
    log = await _get_own_or_manage(db, ctx, log_id)
    await db.delete(log)
    await db.commit()


@me_router.get("/work-logs", response_model=Page[WorkLogOut], summary="Log công việc của tôi (mọi dự án)")
async def my_work_logs(
    date_from: date | None = None,
    date_to: date | None = None,
    project_id: int | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(WorkLog)
    if project_id is not None:
        stmt = stmt.where(WorkLog.project_id == project_id)
    stmt = _filter(stmt, user_id=user.id, date_from=date_from, date_to=date_to)
    return await paginate(db, stmt, page, size)
