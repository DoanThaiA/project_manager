from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ProjectContext, has_permission, require_project_permission
from app.db.session import get_db
from app.models import CustomerContact, Requirement, RequirementComment, RequirementStatusHistory, User
from app.models.enums import PriorityLevel, RequirementType
from app.models.enums import RequirementStatus as RS
from app.schemas.common import Page
from app.schemas.requirement import (
    CommentCreate,
    CommentOut,
    CommentUpdate,
    RequirementCreate,
    RequirementDetail,
    RequirementOut,
    RequirementStats,
    RequirementStatusChange,
    RequirementUpdate,
    StatusHistoryOut,
)
from app.schemas.work import ActivityLogOut
from app.services.activity import activity_query, fetch_activity
from app.services.common import apply_update, ensure_member, not_found, paginate

router = APIRouter()

# Luồng trạng thái hợp lệ: trạng thái hiện tại -> các trạng thái được chuyển tới
TRANSITIONS: dict[RS, set[RS]] = {
    RS.new: {RS.analyzing, RS.pending_approval, RS.approved, RS.rejected, RS.cancelled},
    RS.analyzing: {RS.new, RS.pending_approval, RS.approved, RS.rejected, RS.cancelled},
    RS.pending_approval: {RS.analyzing, RS.approved, RS.rejected, RS.cancelled},
    RS.approved: {RS.analyzing, RS.in_progress, RS.cancelled},
    RS.rejected: {RS.new},
    RS.in_progress: {RS.approved, RS.done, RS.cancelled},
    RS.done: {RS.in_progress, RS.closed},
    RS.closed: {RS.in_progress},
    RS.cancelled: {RS.new},
}
# Chuyển sang các trạng thái này cần quyền requirement.approve
APPROVAL_STATUSES = {RS.approved, RS.rejected}

SORTS = {
    "created_at": Requirement.created_at,
    "received_at": Requirement.received_at,
    "due_date": Requirement.due_date,
    "priority": Requirement.priority,
    "code": Requirement.seq_no,
    "business_value": Requirement.business_value,
}


async def get_requirement(db: AsyncSession, project_id: int, requirement_id: int) -> Requirement:
    req = await db.get(Requirement, requirement_id, populate_existing=True)
    if req is None or req.project_id != project_id or req.deleted_at is not None:
        raise not_found("yêu cầu")
    return req


async def _validate_refs(
    db: AsyncSession, ctx: ProjectContext, values: dict, requirement_id: int | None = None
) -> None:
    pid = ctx.project.id
    if "assignee_id" in values:
        await ensure_member(db, pid, values["assignee_id"], "assignee_id")
    if values.get("parent_id"):
        if values["parent_id"] == requirement_id:
            raise HTTPException(status_code=422, detail="Yêu cầu không thể là cha của chính nó")
        await get_requirement(db, pid, values["parent_id"])
    if values.get("customer_contact_id"):
        contact = await db.get(CustomerContact, values["customer_contact_id"])
        if contact is None or (ctx.project.customer_id and contact.customer_id != ctx.project.customer_id):
            raise HTTPException(status_code=422, detail="Người liên hệ không thuộc khách hàng của dự án")


@router.get("", response_model=Page[RequirementOut])
async def list_requirements(
    q: str | None = Query(default=None, description="Tìm theo mã / tiêu đề / mô tả"),
    status_: list[RS] | None = Query(default=None, alias="status"),
    priority: list[PriorityLevel] | None = Query(default=None),
    type_: list[RequirementType] | None = Query(default=None, alias="type"),
    assignee_id: int | None = None,
    tag: str | None = None,
    overdue: bool | None = Query(default=None, description="Chỉ lấy yêu cầu quá hạn"),
    due_before: date | None = None,
    sort: str = Query(default="-received_at", description="Trường sắp xếp, tiền tố '-' = giảm dần"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
    ctx: ProjectContext = Depends(require_project_permission("requirement.view")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Requirement).where(Requirement.project_id == ctx.project.id, Requirement.deleted_at.is_(None))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(Requirement.code.ilike(like), Requirement.title.ilike(like), Requirement.description.ilike(like))
        )
    if status_:
        stmt = stmt.where(Requirement.status.in_(status_))
    if priority:
        stmt = stmt.where(Requirement.priority.in_(priority))
    if type_:
        stmt = stmt.where(Requirement.type.in_(type_))
    if assignee_id:
        stmt = stmt.where(Requirement.assignee_id == assignee_id)
    if tag:
        stmt = stmt.where(Requirement.tags.any(tag))
    if overdue:
        stmt = stmt.where(
            Requirement.due_date < func.current_date(),
            Requirement.status.not_in([RS.done, RS.closed, RS.cancelled, RS.rejected]),
        )
    if due_before:
        stmt = stmt.where(Requirement.due_date <= due_before)

    column = SORTS.get(sort.lstrip("-"))
    if column is None:
        raise HTTPException(status_code=422, detail=f"sort không hợp lệ, chọn một trong: {', '.join(SORTS)}")
    order = column.desc().nulls_last() if sort.startswith("-") else column.asc().nulls_last()
    stmt = stmt.order_by(order, Requirement.id.desc())
    return await paginate(db, stmt, page, size)


@router.post("", response_model=RequirementOut, status_code=status.HTTP_201_CREATED)
async def create_requirement(
    body: RequirementCreate,
    ctx: ProjectContext = Depends(require_project_permission("requirement.create")),
    db: AsyncSession = Depends(get_db),
):
    values = body.model_dump(exclude_none=True)
    await _validate_refs(db, ctx, values)
    req = Requirement(project_id=ctx.project.id, created_by=ctx.user.id, **values)
    db.add(req)
    await db.commit()
    return await get_requirement(db, ctx.project.id, req.id)  # lấy code, customer_id do trigger sinh


@router.get("/{requirement_id}", response_model=RequirementDetail)
async def get_requirement_detail(
    requirement_id: int,
    ctx: ProjectContext = Depends(require_project_permission("requirement.view")),
    db: AsyncSession = Depends(get_db),
):
    req = await get_requirement(db, ctx.project.id, requirement_id)
    stats = (
        (
            await db.execute(
                text(
                    "SELECT work_item_count, work_item_done, logged_hours, coalesce(is_overdue, false) AS is_overdue "
                    "FROM v_requirement_overview WHERE id = :id"
                ),
                {"id": requirement_id},
            )
        )
        .mappings()
        .one()
    )
    return RequirementDetail(**RequirementOut.model_validate(req).model_dump(), stats=RequirementStats(**stats))


@router.patch("/{requirement_id}", response_model=RequirementOut)
async def update_requirement(
    requirement_id: int,
    body: RequirementUpdate,
    ctx: ProjectContext = Depends(require_project_permission("requirement.update")),
    db: AsyncSession = Depends(get_db),
):
    req = await get_requirement(db, ctx.project.id, requirement_id)
    values = body.model_dump(exclude_unset=True)
    if "assignee_id" in values and not await has_permission(db, ctx.user, "requirement.assign", ctx.project.id):
        raise HTTPException(status_code=403, detail="Yêu cầu quyền 'requirement.assign'")
    await _validate_refs(db, ctx, values, requirement_id)
    apply_update(req, body)
    await db.commit()
    return req


@router.delete("/{requirement_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Xoá mềm yêu cầu")
async def delete_requirement(
    requirement_id: int,
    ctx: ProjectContext = Depends(require_project_permission("requirement.delete")),
    db: AsyncSession = Depends(get_db),
):
    req = await get_requirement(db, ctx.project.id, requirement_id)
    req.deleted_at = func.now()
    await db.commit()


@router.post("/{requirement_id}/status", response_model=RequirementOut, summary="Chuyển trạng thái yêu cầu")
async def change_status(
    requirement_id: int,
    body: RequirementStatusChange,
    ctx: ProjectContext = Depends(require_project_permission("requirement.update")),
    db: AsyncSession = Depends(get_db),
):
    req = await get_requirement(db, ctx.project.id, requirement_id)
    if body.status == req.status:
        raise HTTPException(status_code=409, detail=f"Yêu cầu đã ở trạng thái '{req.status}'")
    if body.status not in TRANSITIONS[req.status]:
        allowed = ", ".join(sorted(TRANSITIONS[req.status]))
        raise HTTPException(
            status_code=409, detail=f"Không thể chuyển '{req.status}' -> '{body.status}'. Được phép: {allowed}"
        )
    if body.status in APPROVAL_STATUSES and not await has_permission(
        db, ctx.user, "requirement.approve", ctx.project.id
    ):
        raise HTTPException(status_code=403, detail="Yêu cầu quyền 'requirement.approve' để duyệt / từ chối")
    if body.status == RS.rejected:
        if not body.rejected_reason:
            raise HTTPException(status_code=422, detail="Cần nhập rejected_reason khi từ chối")
        req.rejected_reason = body.rejected_reason
    if body.status == RS.new:  # mở lại -> xoá dấu vết duyệt / đóng
        req.rejected_reason = req.approved_at = req.approved_by = req.closed_at = req.resolved_at = None
    if body.status == RS.in_progress:
        req.resolved_at = req.closed_at = None

    await db.execute(text("SELECT set_config('app.status_note', :note, true)"), {"note": body.note or ""})
    req.status = body.status
    await db.commit()
    return await get_requirement(db, ctx.project.id, requirement_id)  # lấy approved_at... do trigger set


@router.get("/{requirement_id}/history", response_model=list[StatusHistoryOut], summary="Lịch sử trạng thái")
async def status_history(
    requirement_id: int,
    ctx: ProjectContext = Depends(require_project_permission("requirement.view")),
    db: AsyncSession = Depends(get_db),
):
    await get_requirement(db, ctx.project.id, requirement_id)
    rows = await db.execute(
        select(RequirementStatusHistory, User.full_name)
        .outerjoin(User, User.id == RequirementStatusHistory.changed_by)
        .where(RequirementStatusHistory.requirement_id == requirement_id)
        .order_by(RequirementStatusHistory.changed_at, RequirementStatusHistory.id)
    )
    result = []
    for history, name in rows.all():
        item = StatusHistoryOut.model_validate(history)
        item.changed_by_name = name
        result.append(item)
    return result


@router.get("/{requirement_id}/activity", response_model=Page[ActivityLogOut], summary="Nhật ký thay đổi của yêu cầu")
async def requirement_activity(
    requirement_id: int,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    ctx: ProjectContext = Depends(require_project_permission("requirement.view")),
    db: AsyncSession = Depends(get_db),
):
    await get_requirement(db, ctx.project.id, requirement_id)
    stmt = activity_query(entity_type="requirements", entity_id=requirement_id)
    return await fetch_activity(db, stmt, page, size)


# ---------------------------------------------------------------- Bình luận
async def _get_comment(db: AsyncSession, requirement_id: int, comment_id: int) -> RequirementComment:
    comment = await db.get(RequirementComment, comment_id)
    if comment is None or comment.requirement_id != requirement_id or comment.deleted_at is not None:
        raise not_found("bình luận")
    return comment


def _comment_out(comment: RequirementComment, user_name: str | None) -> CommentOut:
    out = CommentOut.model_validate(comment)
    out.user_name = user_name
    return out


@router.get("/{requirement_id}/comments", response_model=list[CommentOut])
async def list_comments(
    requirement_id: int,
    ctx: ProjectContext = Depends(require_project_permission("requirement.view")),
    db: AsyncSession = Depends(get_db),
):
    await get_requirement(db, ctx.project.id, requirement_id)
    stmt = (
        select(RequirementComment, User.full_name)
        .outerjoin(User, User.id == RequirementComment.user_id)
        .where(RequirementComment.requirement_id == requirement_id, RequirementComment.deleted_at.is_(None))
        .order_by(RequirementComment.created_at, RequirementComment.id)
    )
    if not await has_permission(db, ctx.user, "requirement.view_internal", ctx.project.id):
        stmt = stmt.where(RequirementComment.is_internal.is_(False))
    return [_comment_out(c, name) for c, name in (await db.execute(stmt)).all()]


@router.post("/{requirement_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
async def create_comment(
    requirement_id: int,
    body: CommentCreate,
    ctx: ProjectContext = Depends(require_project_permission("requirement.comment")),
    db: AsyncSession = Depends(get_db),
):
    await get_requirement(db, ctx.project.id, requirement_id)
    if body.is_internal and not await has_permission(db, ctx.user, "requirement.view_internal", ctx.project.id):
        raise HTTPException(status_code=403, detail="Không có quyền tạo bình luận nội bộ")
    if body.parent_id:
        await _get_comment(db, requirement_id, body.parent_id)
    comment = RequirementComment(requirement_id=requirement_id, user_id=ctx.user.id, **body.model_dump())
    db.add(comment)
    await db.commit()
    return _comment_out(comment, ctx.user.full_name)


@router.patch("/{requirement_id}/comments/{comment_id}", response_model=CommentOut)
async def update_comment(
    requirement_id: int,
    comment_id: int,
    body: CommentUpdate,
    ctx: ProjectContext = Depends(require_project_permission("requirement.comment")),
    db: AsyncSession = Depends(get_db),
):
    comment = await _get_comment(db, requirement_id, comment_id)
    if comment.user_id != ctx.user.id:
        raise HTTPException(status_code=403, detail="Chỉ sửa được bình luận của mình")
    comment.content = body.content
    await db.commit()
    return _comment_out(comment, ctx.user.full_name)


@router.delete("/{requirement_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    requirement_id: int,
    comment_id: int,
    ctx: ProjectContext = Depends(require_project_permission("requirement.comment")),
    db: AsyncSession = Depends(get_db),
):
    comment = await _get_comment(db, requirement_id, comment_id)
    if comment.user_id != ctx.user.id and not ctx.user.is_system_admin:
        raise HTTPException(status_code=403, detail="Chỉ xoá được bình luận của mình")
    comment.deleted_at = func.now()
    await db.commit()
