from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ProjectContext, require_project_permission
from app.db.session import get_db
from app.models import Project, Sprint, WorkItem
from app.models.enums import SprintStatus, WorkItemStatus
from app.schemas.project import SprintComplete, SprintCreate, SprintOut, SprintProgress, SprintUpdate
from app.services.common import apply_update, not_found

router = APIRouter()


async def _get_sprint(db: AsyncSession, project_id: int, sprint_id: int) -> Sprint:
    sprint = await db.get(Sprint, sprint_id)
    if sprint is None or sprint.project_id != project_id:
        raise not_found("sprint")
    return sprint


@router.get("", response_model=list[SprintOut])
async def list_sprints(
    status_: SprintStatus | None = Query(default=None, alias="status"),
    ctx: ProjectContext = Depends(require_project_permission("sprint.view")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Sprint).where(Sprint.project_id == ctx.project.id).order_by(Sprint.sprint_no.desc())
    if status_:
        stmt = stmt.where(Sprint.status == status_)
    return (await db.scalars(stmt)).all()


@router.post("", response_model=SprintOut, status_code=status.HTTP_201_CREATED)
async def create_sprint(
    body: SprintCreate,
    ctx: ProjectContext = Depends(require_project_permission("sprint.manage")),
    db: AsyncSession = Depends(get_db),
):
    project = ctx.project
    # Khoá dòng dự án để sinh sprint_no không bị trùng khi tạo đồng thời
    await db.execute(select(Project.id).where(Project.id == project.id).with_for_update())
    next_no = await db.scalar(
        select(func.coalesce(func.max(Sprint.sprint_no), 0) + 1).where(Sprint.project_id == project.id)
    )
    sprint = Sprint(
        project_id=project.id,
        sprint_no=next_no,
        name=body.name or f"Sprint {next_no}",
        goal=body.goal,
        start_date=body.start_date,
        end_date=body.end_date or body.start_date + timedelta(days=project.sprint_duration_days - 1),
        capacity_hours=body.capacity_hours,
        created_by=ctx.user.id,
    )
    db.add(sprint)
    await db.commit()
    return sprint


@router.get("/{sprint_id}", response_model=SprintOut)
async def get_sprint(
    sprint_id: int,
    ctx: ProjectContext = Depends(require_project_permission("sprint.view")),
    db: AsyncSession = Depends(get_db),
):
    return await _get_sprint(db, ctx.project.id, sprint_id)


@router.patch("/{sprint_id}", response_model=SprintOut)
async def update_sprint(
    sprint_id: int,
    body: SprintUpdate,
    ctx: ProjectContext = Depends(require_project_permission("sprint.manage")),
    db: AsyncSession = Depends(get_db),
):
    sprint = await _get_sprint(db, ctx.project.id, sprint_id)
    apply_update(sprint, body)
    if sprint.end_date < sprint.start_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="end_date phải >= start_date")
    await db.commit()
    return sprint


@router.post("/{sprint_id}/start", response_model=SprintOut, summary="Bắt đầu sprint (mỗi dự án 1 sprint active)")
async def start_sprint(
    sprint_id: int,
    ctx: ProjectContext = Depends(require_project_permission("sprint.manage")),
    db: AsyncSession = Depends(get_db),
):
    sprint = await _get_sprint(db, ctx.project.id, sprint_id)
    if sprint.status != SprintStatus.planned:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Chỉ bắt đầu được sprint ở trạng thái planned")
    active = await db.scalar(
        select(Sprint.name).where(Sprint.project_id == ctx.project.id, Sprint.status == SprintStatus.active)
    )
    if active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Dự án đang có sprint chạy: {active}")
    sprint.status = SprintStatus.active
    # Công việc trong sprint đang ở backlog -> todo
    await db.execute(
        update(WorkItem)
        .where(WorkItem.sprint_id == sprint.id, WorkItem.status == WorkItemStatus.backlog)
        .values(status=WorkItemStatus.todo)
    )
    await db.commit()
    return sprint


@router.post(
    "/{sprint_id}/complete",
    response_model=SprintOut,
    summary="Kết thúc sprint, chuyển việc chưa xong về backlog hoặc sprint kế tiếp",
)
async def complete_sprint(
    sprint_id: int,
    body: SprintComplete,
    ctx: ProjectContext = Depends(require_project_permission("sprint.manage")),
    db: AsyncSession = Depends(get_db),
):
    sprint = await _get_sprint(db, ctx.project.id, sprint_id)
    if sprint.status != SprintStatus.active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Chỉ kết thúc được sprint đang active")

    unfinished = update(WorkItem).where(
        WorkItem.sprint_id == sprint.id,
        WorkItem.status.not_in([WorkItemStatus.done, WorkItemStatus.cancelled]),
        WorkItem.deleted_at.is_(None),
    )
    if body.move_unfinished_to == "next_sprint":
        target = await _get_sprint(db, ctx.project.id, body.next_sprint_id)  # type: ignore[arg-type]
        if target.status != SprintStatus.planned:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Sprint đích phải ở trạng thái planned")
        await db.execute(unfinished.values(sprint_id=target.id))
    else:
        await db.execute(unfinished.values(sprint_id=None, status=WorkItemStatus.backlog))

    sprint.status = SprintStatus.completed
    if body.review_note is not None:
        sprint.review_note = body.review_note
    if body.retrospective_note is not None:
        sprint.retrospective_note = body.retrospective_note
    await db.commit()
    return sprint


@router.get("/{sprint_id}/progress", response_model=SprintProgress)
async def sprint_progress(
    sprint_id: int,
    ctx: ProjectContext = Depends(require_project_permission("sprint.view")),
    db: AsyncSession = Depends(get_db),
):
    await _get_sprint(db, ctx.project.id, sprint_id)
    result = await db.execute(text("SELECT * FROM v_sprint_progress WHERE sprint_id = :id"), {"id": sprint_id})
    row = result.mappings().one()
    return SprintProgress(**row)
