from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, text, update
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

FINISHED = (WorkItemStatus.done, WorkItemStatus.cancelled)
NOT_STARTED = (WorkItemStatus.backlog, WorkItemStatus.todo)
CLOSED_SPRINT = (SprintStatus.completed, SprintStatus.cancelled)


async def get_work_item(db: AsyncSession, project_id: int, item_id: int) -> WorkItem:
    item = await db.get(WorkItem, item_id, populate_existing=True)
    if item is None or item.project_id != project_id or item.deleted_at is not None:
        raise not_found("công việc")
    return item


async def _validate_refs(db: AsyncSession, ctx: ProjectContext, values: dict, item_id: int | None = None) -> None:
    pid = ctx.project.id
    for user_id in values.get("assignee_ids") or []:
        await ensure_member(db, pid, user_id, "assignee_ids")
    if values.get("requirement_id"):
        await get_requirement(db, pid, values["requirement_id"])
    if values.get("sprint_id"):
        sprint = await db.get(Sprint, values["sprint_id"])
        if sprint is None or sprint.project_id != pid:
            raise not_found("sprint")
        if sprint.status in CLOSED_SPRINT:
            raise HTTPException(status_code=409, detail="Không thể thêm việc vào sprint đã kết thúc / huỷ")


async def _check_assignees(db: AsyncSession, ctx: ProjectContext, values: dict, old: list[int]) -> None:
    """Bỏ trùng người phụ trách; thêm / gỡ người khác (ngoài chính mình) cần quyền 'work_item.assign'."""
    if values.get("assignee_ids") is None:
        values.pop("assignee_ids", None)
        return
    values["assignee_ids"] = list(dict.fromkeys(values["assignee_ids"]))
    changed = set(values["assignee_ids"]) ^ set(old)
    if changed - {ctx.user.id} and not await has_permission(db, ctx.user, "work_item.assign", ctx.project.id):
        raise HTTPException(status_code=403, detail="Yêu cầu quyền 'work_item.assign' để giao việc cho người khác")


async def _check_parent(db: AsyncSession, project_id: int, parent_id: int, item_id: int | None) -> WorkItem:
    """Công việc cha hợp lệ cho subtask (`item_id`: công việc đang được gắn làm subtask, None khi tạo mới)."""
    if parent_id == item_id:
        raise HTTPException(status_code=422, detail="Công việc không thể là cha của chính nó")
    parent = await get_work_item(db, project_id, parent_id)
    # Subtask chỉ một cấp: không tạo subtask cho subtask, công việc đã có subtask không thành subtask được
    if parent.parent_id is not None or parent.type == WorkItemType.subtask:
        raise HTTPException(status_code=422, detail="Không thể tạo subtask cho một subtask")
    if item_id is not None and await _subtask_statuses(db, item_id):
        raise HTTPException(status_code=422, detail="Công việc đang có subtask nên không thể làm subtask")
    if parent.status == WorkItemStatus.cancelled:
        raise HTTPException(status_code=422, detail=f"{parent.code} đã huỷ, không thêm subtask được")
    # Subtask đi theo sprint của cha: cha nằm trong sprint đã kết thúc thì không thêm vào được nữa
    if parent.sprint_id is not None:
        sprint = await db.get(Sprint, parent.sprint_id)
        if sprint is not None and sprint.status in CLOSED_SPRINT:
            raise HTTPException(
                status_code=409, detail=f"{parent.code} thuộc sprint đã kết thúc, không thêm subtask được"
            )
    return parent


async def _subtask_statuses(db: AsyncSession, parent_id: int) -> list[WorkItemStatus]:
    rows = await db.scalars(
        select(WorkItem.status).where(WorkItem.parent_id == parent_id, WorkItem.deleted_at.is_(None))
    )
    return list(rows)


async def _sync_parent(db: AsyncSession, parent_id: int | None) -> None:
    """Đồng bộ trạng thái công việc cha theo các subtask.

    - Mọi subtask đã xong / huỷ (ít nhất một xong) -> cha 'done'
    - Còn subtask chưa xong mà cha đang 'done' -> cha mở lại 'in_progress'
    - Có subtask đã bắt đầu mà cha còn backlog / todo -> cha 'in_progress'
    Cha đã huỷ thì giữ nguyên.
    """
    if parent_id is None:
        return
    parent = await db.get(WorkItem, parent_id, populate_existing=True)
    if parent is None or parent.deleted_at is not None or parent.status == WorkItemStatus.cancelled:
        return
    statuses = await _subtask_statuses(db, parent_id)
    if not statuses:
        return
    finished = all(s in FINISHED for s in statuses)
    started = any(s not in NOT_STARTED and s != WorkItemStatus.cancelled for s in statuses)
    if finished and WorkItemStatus.done in statuses:
        new = WorkItemStatus.done
    elif (parent.status == WorkItemStatus.done and not finished) or (parent.status in NOT_STARTED and started):
        new = WorkItemStatus.in_progress
    else:
        return
    if parent.status != new:
        parent.status = new
        await db.flush()
        await _sync_requirement(db, parent)


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
        stmt = stmt.where(WorkItem.assignee_ids.contains([assignee_id]))
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
    await _check_assignees(db, ctx, values, [])
    if body.type == WorkItemType.subtask and not body.parent_id:
        raise HTTPException(status_code=422, detail="Subtask phải chọn công việc cha")
    if body.parent_id:
        await _inherit_from_parent(db, ctx.project.id, body, values)
    await _validate_refs(db, ctx, values)
    values.setdefault("status", WorkItemStatus.todo if values.get("sprint_id") else WorkItemStatus.backlog)
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
    await _sync_parent(db, item.parent_id)
    await db.commit()
    return await get_work_item(db, ctx.project.id, item.id)


async def _inherit_from_parent(db: AsyncSession, project_id: int, body: WorkItemCreate, values: dict) -> None:
    """Subtask mới: loại 'subtask', luôn cùng sprint với công việc cha, mặc định cùng yêu cầu khách hàng."""
    parent = await _check_parent(db, project_id, body.parent_id, None)
    values["type"] = WorkItemType.subtask
    if parent.sprint_id is None:
        values.pop("sprint_id", None)
    else:
        values["sprint_id"] = parent.sprint_id
    if body.requirement_id is None and parent.requirement_id:
        values["requirement_id"] = parent.requirement_id


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
    await _check_assignees(db, ctx, values, item.assignee_ids)
    old_parent_id = item.parent_id
    await _resolve_parent(db, ctx.project.id, item, values)
    await _validate_refs(db, ctx, values, item_id)

    subtasks = await _subtask_statuses(db, item_id)
    if values.get("status") == WorkItemStatus.done and (open_count := sum(s not in FINISHED for s in subtasks)):
        raise HTTPException(
            status_code=409,
            detail=f"Còn {open_count} subtask chưa xong — công việc tự chuyển 'Xong' khi mọi subtask xong",
        )

    # Di chuyển giữa sprint <-> backlog thì đồng bộ trạng thái
    if "sprint_id" in values and "status" not in values:
        if values["sprint_id"] is None and item.status not in (WorkItemStatus.done, WorkItemStatus.cancelled):
            values["status"] = WorkItemStatus.backlog
        elif values["sprint_id"] is not None and item.status == WorkItemStatus.backlog:
            values["status"] = WorkItemStatus.todo

    for field, value in values.items():
        setattr(item, field, value)
    await db.flush()
    if "sprint_id" in values and subtasks:
        await _move_subtasks(db, item)
    if values.get("status") == WorkItemStatus.cancelled and subtasks:
        # Huỷ công việc cha thì huỷ luôn các subtask chưa xong
        await db.execute(
            update(WorkItem)
            .where(WorkItem.parent_id == item.id, WorkItem.deleted_at.is_(None), WorkItem.status.not_in(FINISHED))
            .values(status=WorkItemStatus.cancelled)
            .execution_options(synchronize_session=False)
        )
    await _sync_requirement(db, item)
    await _sync_parent(db, item.parent_id)
    if old_parent_id != item.parent_id:
        await _sync_parent(db, old_parent_id)
    await db.commit()
    return await get_work_item(db, ctx.project.id, item_id)  # completed_at do trigger set


async def _resolve_parent(db: AsyncSession, project_id: int, item: WorkItem, values: dict) -> None:
    """Giữ nhất quán khi sửa: loại 'subtask' <=> có công việc cha, và subtask luôn cùng sprint với cha.

    - Gắn công việc cha -> loại thành 'subtask', sprint theo cha
    - Đổi loại khác 'subtask' -> gỡ khỏi công việc cha; gỡ cha mà không đổi loại -> thành 'task'
    - Đổi sprint riêng cho subtask -> báo lỗi (đổi sprint ở công việc cha, subtask đi theo)
    """
    if values.get("parent_id") is not None:
        values["type"] = WorkItemType.subtask
    elif "type" in values and values["type"] != WorkItemType.subtask:
        if item.parent_id is not None:
            values["parent_id"] = None
    elif "parent_id" in values and item.type == WorkItemType.subtask and "type" not in values:
        values["type"] = WorkItemType.task

    parent_id = values.get("parent_id", item.parent_id)
    if values.get("type", item.type) == WorkItemType.subtask and parent_id is None:
        raise HTTPException(status_code=422, detail="Subtask phải chọn công việc cha")
    if parent_id is None:
        return
    if parent_id != item.parent_id:
        parent = await _check_parent(db, project_id, parent_id, item.id)
        if values.get("sprint_id", parent.sprint_id) != parent.sprint_id:
            raise HTTPException(status_code=422, detail="Subtask phải cùng sprint với công việc cha")
        if parent.sprint_id != item.sprint_id:
            values["sprint_id"] = parent.sprint_id
        else:
            values.pop("sprint_id", None)
    elif "sprint_id" in values and values["sprint_id"] != item.sprint_id:
        raise HTTPException(
            status_code=422, detail="Subtask đi theo sprint của công việc cha — hãy đổi sprint ở công việc cha"
        )
    elif item.status in FINISHED and values.get("status") not in (None, *FINISHED):
        # Subtask đã xong nằm lại sprint cũ khi cha chuyển sprint; mở lại thì về cùng sprint với cha
        parent = await get_work_item(db, project_id, parent_id)
        if parent.sprint_id != item.sprint_id:
            values["sprint_id"] = parent.sprint_id


async def _move_subtasks(db: AsyncSession, parent: WorkItem) -> None:
    """Công việc cha đổi sprint -> các subtask chưa xong đi theo (cùng quy tắc trạng thái sprint <-> backlog)."""
    unfinished = (
        update(WorkItem)
        .where(WorkItem.parent_id == parent.id, WorkItem.deleted_at.is_(None), WorkItem.status.not_in(FINISHED))
        .execution_options(synchronize_session=False)
    )
    if parent.sprint_id is None:
        await db.execute(unfinished.values(sprint_id=None, status=WorkItemStatus.backlog))
    else:
        await db.execute(
            unfinished.where(WorkItem.status == WorkItemStatus.backlog).values(
                sprint_id=parent.sprint_id, status=WorkItemStatus.todo
            )
        )
        await db.execute(unfinished.values(sprint_id=parent.sprint_id))


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Xoá mềm công việc")
async def delete_work_item(
    item_id: int,
    ctx: ProjectContext = Depends(require_project_permission("work_item.delete")),
    db: AsyncSession = Depends(get_db),
):
    item = await get_work_item(db, ctx.project.id, item_id)
    item.deleted_at = func.now()
    # Xoá công việc cha thì xoá luôn các subtask
    await db.execute(
        update(WorkItem)
        .where(WorkItem.parent_id == item_id, WorkItem.deleted_at.is_(None))
        .values(deleted_at=func.now())
        .execution_options(synchronize_session=False)
    )
    await db.flush()
    await _sync_parent(db, item.parent_id)
    await db.commit()
