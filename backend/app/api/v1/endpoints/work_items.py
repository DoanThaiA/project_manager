from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ProjectContext, has_permission, require_project_permission
from app.api.v1.endpoints.requirements import get_requirement
from app.db.session import get_db
from app.models import Requirement, Sprint, WorkItem
from app.models.enums import RequirementStatus, SprintStatus, WorkItemStatus, WorkItemType
from app.schemas.common import Page
from app.schemas.work import WorkItemCreate, WorkItemOut, WorkItemUpdate
from app.services.common import ensure_member, not_found, paginate

router = APIRouter()


async def get_work_item(db: AsyncSession, project_id: int, item_id: int) -> WorkItem:
    item = await db.get(WorkItem, item_id, populate_existing=True)
    if item is None or item.project_id != project_id or item.deleted_at is not None:
        raise not_found("công việc")
    return item


async def _validate_refs(db: AsyncSession, ctx: ProjectContext, values: dict, item_id: int | None = None) -> None:
    pid = ctx.project.id
    if "assignee_id" in values:
        await ensure_member(db, pid, values["assignee_id"], "assignee_id")
    if values.get("requirement_id"):
        await get_requirement(db, pid, values["requirement_id"])
    if values.get("sprint_id"):
        sprint = await db.get(Sprint, values["sprint_id"])
        if sprint is None or sprint.project_id != pid:
            raise not_found("sprint")
        if sprint.status in (SprintStatus.completed, SprintStatus.cancelled):
            raise HTTPException(status_code=409, detail="Không thể thêm việc vào sprint đã kết thúc / huỷ")
    if values.get("parent_id"):
        if values["parent_id"] == item_id:
            raise HTTPException(status_code=422, detail="Công việc không thể là cha của chính nó")
        await get_work_item(db, pid, values["parent_id"])


async def _sync_requirement(db: AsyncSession, item: WorkItem) -> None:
    """Công việc bắt đầu làm -> yêu cầu gốc đang 'approved' tự chuyển 'in_progress'."""
    if item.requirement_id is None or item.status not in (
        WorkItemStatus.in_progress,
        WorkItemStatus.in_review,
        WorkItemStatus.testing,
        WorkItemStatus.done,
    ):
        return
    req = await db.get(Requirement, item.requirement_id)
    if req is not None and req.status == RequirementStatus.approved:
        await db.execute(
            text("SELECT set_config('app.status_note', :note, true)"),
            {"note": f"Tự động: {item.code} bắt đầu thực hiện"},
        )
        req.status = RequirementStatus.in_progress


@router.get("", response_model=Page[WorkItemOut])
async def list_work_items(
    q: str | None = None,
    sprint_id: int | None = None,
    backlog: bool | None = Query(default=None, description="true: chỉ lấy Product Backlog (chưa vào sprint)"),
    status_: list[WorkItemStatus] | None = Query(default=None, alias="status"),
    type_: list[WorkItemType] | None = Query(default=None, alias="type"),
    assignee_id: int | None = None,
    requirement_id: int | None = None,
    parent_id: int | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=500),
    ctx: ProjectContext = Depends(require_project_permission("work_item.view")),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(WorkItem)
        .where(WorkItem.project_id == ctx.project.id, WorkItem.deleted_at.is_(None))
        .order_by(WorkItem.backlog_rank, WorkItem.id)
    )
    if q:
        stmt = stmt.where(or_(WorkItem.code.ilike(f"%{q}%"), WorkItem.title.ilike(f"%{q}%")))
    if sprint_id is not None:
        stmt = stmt.where(WorkItem.sprint_id == sprint_id)
    if backlog is True:
        stmt = stmt.where(WorkItem.sprint_id.is_(None))
    elif backlog is False:
        stmt = stmt.where(WorkItem.sprint_id.is_not(None))
    if status_:
        stmt = stmt.where(WorkItem.status.in_(status_))
    if type_:
        stmt = stmt.where(WorkItem.type.in_(type_))
    if assignee_id is not None:
        stmt = stmt.where(WorkItem.assignee_id == assignee_id)
    if requirement_id is not None:
        stmt = stmt.where(WorkItem.requirement_id == requirement_id)
    if parent_id is not None:
        stmt = stmt.where(WorkItem.parent_id == parent_id)
    return await paginate(db, stmt, page, size)


@router.post("", response_model=WorkItemOut, status_code=status.HTTP_201_CREATED)
async def create_work_item(
    body: WorkItemCreate,
    ctx: ProjectContext = Depends(require_project_permission("work_item.create")),
    db: AsyncSession = Depends(get_db),
):
    values = body.model_dump(exclude_none=True)
    if body.assignee_id not in (None, ctx.user.id) and not await has_permission(
        db, ctx.user, "work_item.assign", ctx.project.id
    ):
        raise HTTPException(status_code=403, detail="Yêu cầu quyền 'work_item.assign' để giao việc cho người khác")
    await _validate_refs(db, ctx, values)
    values.setdefault("status", WorkItemStatus.todo if body.sprint_id else WorkItemStatus.backlog)
    if body.backlog_rank is None:
        values["backlog_rank"] = await db.scalar(
            select(func.coalesce(func.max(WorkItem.backlog_rank), 0) + 1).where(WorkItem.project_id == ctx.project.id)
        )
    if body.original_estimate_hours is not None and body.remaining_hours is None:
        values["remaining_hours"] = body.original_estimate_hours

    item = WorkItem(project_id=ctx.project.id, reporter_id=ctx.user.id, **values)
    db.add(item)
    await db.flush()
    await _sync_requirement(db, item)
    await db.commit()
    return item


@router.get("/{item_id}", response_model=WorkItemOut)
async def get_work_item_detail(
    item_id: int,
    ctx: ProjectContext = Depends(require_project_permission("work_item.view")),
    db: AsyncSession = Depends(get_db),
):
    return await get_work_item(db, ctx.project.id, item_id)


@router.patch("/{item_id}", response_model=WorkItemOut)
async def update_work_item(
    item_id: int,
    body: WorkItemUpdate,
    ctx: ProjectContext = Depends(require_project_permission("work_item.update")),
    db: AsyncSession = Depends(get_db),
):
    item = await get_work_item(db, ctx.project.id, item_id)
    values = body.model_dump(exclude_unset=True)
    if (
        "assignee_id" in values
        and values["assignee_id"] not in (None, ctx.user.id)
        and not await has_permission(db, ctx.user, "work_item.assign", ctx.project.id)
    ):
        raise HTTPException(status_code=403, detail="Yêu cầu quyền 'work_item.assign' để giao việc cho người khác")
    await _validate_refs(db, ctx, values, item_id)

    # Di chuyển giữa sprint <-> backlog thì đồng bộ trạng thái
    if "sprint_id" in values and "status" not in values:
        if values["sprint_id"] is None and item.status not in (WorkItemStatus.done, WorkItemStatus.cancelled):
            values["status"] = WorkItemStatus.backlog
        elif values["sprint_id"] is not None and item.status == WorkItemStatus.backlog:
            values["status"] = WorkItemStatus.todo

    for field, value in values.items():
        setattr(item, field, value)
    await db.flush()
    await _sync_requirement(db, item)
    await db.commit()
    return await get_work_item(db, ctx.project.id, item_id)  # completed_at do trigger set


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Xoá mềm công việc")
async def delete_work_item(
    item_id: int,
    ctx: ProjectContext = Depends(require_project_permission("work_item.delete")),
    db: AsyncSession = Depends(get_db),
):
    item = await get_work_item(db, ctx.project.id, item_id)
    item.deleted_at = func.now()
    await db.commit()
