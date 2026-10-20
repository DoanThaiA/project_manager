from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    ProjectContext,
    get_current_user,
    has_permission,
    permission_codes,
    require_permission,
    require_project_permission,
)
from app.db.session import get_db
from app.models import Project, ProjectMember, Role, User
from app.models.enums import ProjectStatus, RoleScope
from app.schemas.common import Page
from app.schemas.project import MemberAdd, MemberOut, ProjectCreate, ProjectOut, ProjectUpdate
from app.schemas.user import RoleOut, UserBrief
from app.services.common import apply_update, ensure_member, paginate

router = APIRouter()


async def _role_id(db: AsyncSession, code: str) -> int:
    return (await db.execute(select(Role.id).where(Role.code == code))).scalar_one()


@router.get("", response_model=Page[ProjectOut], summary="Dự án mà người dùng được xem")
async def list_projects(
    q: str | None = None,
    status_: ProjectStatus | None = Query(default=None, alias="status"),
    customer_id: int | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Project).where(Project.deleted_at.is_(None)).order_by(Project.created_at.desc())
    # Quyền project.view cấp hệ thống -> thấy tất cả; ngược lại chỉ dự án mình tham gia
    if not await has_permission(db, user, "project.view"):
        stmt = stmt.where(exists().where(ProjectMember.project_id == Project.id, ProjectMember.user_id == user.id))
    if q:
        stmt = stmt.where(or_(Project.key.ilike(f"%{q}%"), Project.name.ilike(f"%{q}%")))
    if status_:
        stmt = stmt.where(Project.status == status_)
    if customer_id:
        stmt = stmt.where(Project.customer_id == customer_id)
    return await paginate(db, stmt, page, size)


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    user: User = Depends(require_permission("project.create")),
    db: AsyncSession = Depends(get_db),
):
    project = Project(**body.model_dump(), created_by=user.id)
    project.product_owner_id = project.product_owner_id or user.id
    db.add(project)
    await db.flush()

    members = {(project.product_owner_id, await _role_id(db, "PRODUCT_OWNER"))}
    if project.scrum_master_id:
        members.add((project.scrum_master_id, await _role_id(db, "SCRUM_MASTER")))
    db.add_all(ProjectMember(project_id=project.id, user_id=uid, role_id=rid, added_by=user.id) for uid, rid in members)
    await db.commit()
    return project


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(ctx: ProjectContext = Depends(require_project_permission("project.view"))):
    return ctx.project


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    body: ProjectUpdate,
    ctx: ProjectContext = Depends(require_project_permission("project.update")),
    db: AsyncSession = Depends(get_db),
):
    project = ctx.project
    values = apply_update(project, body)
    # PO / SM mới phải là thành viên với đúng vai trò
    for field, role_code in (("product_owner_id", "PRODUCT_OWNER"), ("scrum_master_id", "SCRUM_MASTER")):
        if values.get(field):
            role_id = await _role_id(db, role_code)
            already = await db.get(ProjectMember, (project.id, values[field], role_id))
            if already is None:
                db.add(
                    ProjectMember(project_id=project.id, user_id=values[field], role_id=role_id, added_by=ctx.user.id)
                )
    await db.commit()
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Xoá mềm dự án")
async def delete_project(
    ctx: ProjectContext = Depends(require_project_permission("project.delete")),
    db: AsyncSession = Depends(get_db),
):
    ctx.project.deleted_at = func.now()
    await db.commit()


@router.get("/{project_id}/my-permissions", response_model=list[str], summary="Quyền của tôi trong dự án")
async def my_permissions(
    ctx: ProjectContext = Depends(require_project_permission("project.view")),
    db: AsyncSession = Depends(get_db),
):
    return await permission_codes(db, ctx.user, ctx.project.id)


# ---------------------------------------------------------------- Thành viên
@router.get("/{project_id}/members", response_model=list[MemberOut])
async def list_members(
    ctx: ProjectContext = Depends(require_project_permission("project.view")),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(ProjectMember, User, Role)
        .join(User, User.id == ProjectMember.user_id)
        .join(Role, Role.id == ProjectMember.role_id)
        .where(ProjectMember.project_id == ctx.project.id)
        .order_by(User.full_name, Role.id)
    )
    grouped: dict[int, MemberOut] = {}
    roles: dict[int, list[RoleOut]] = defaultdict(list)
    for member, user, role in rows.all():
        roles[user.id].append(RoleOut.model_validate(role))
        if user.id not in grouped:
            grouped[user.id] = MemberOut(user=UserBrief.model_validate(user), roles=[], joined_at=member.joined_at)
        grouped[user.id].joined_at = min(grouped[user.id].joined_at, member.joined_at)
    for uid, m in grouped.items():
        m.roles = roles[uid]
    return list(grouped.values())


@router.post(
    "/{project_id}/members",
    response_model=list[MemberOut],
    status_code=status.HTTP_201_CREATED,
    summary="Thêm thành viên / thêm vai trò cho thành viên",
)
async def add_member(
    body: MemberAdd,
    ctx: ProjectContext = Depends(require_project_permission("project.member.manage")),
    db: AsyncSession = Depends(get_db),
):
    target = await db.get(User, body.user_id)
    if target is None or target.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy người dùng")
    role_ids = list(dict.fromkeys(body.role_ids))
    valid = set((await db.scalars(select(Role.id).where(Role.id.in_(role_ids), Role.scope == RoleScope.project))).all())
    if invalid := set(role_ids) - valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Vai trò không tồn tại hoặc không phải vai trò dự án: {sorted(invalid)}",
        )
    for rid in role_ids:
        if await db.get(ProjectMember, (ctx.project.id, body.user_id, rid)) is None:
            db.add(ProjectMember(project_id=ctx.project.id, user_id=body.user_id, role_id=rid, added_by=ctx.user.id))
    await db.commit()
    return await list_members(ctx, db)


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Xoá thành viên (hoặc chỉ một vai trò nếu truyền role_id)",
)
async def remove_member(
    user_id: int,
    role_id: int | None = None,
    ctx: ProjectContext = Depends(require_project_permission("project.member.manage")),
    db: AsyncSession = Depends(get_db),
):
    await ensure_member(db, ctx.project.id, user_id)
    stmt = delete(ProjectMember).where(ProjectMember.project_id == ctx.project.id, ProjectMember.user_id == user_id)
    if role_id is not None:
        stmt = stmt.where(ProjectMember.role_id == role_id)
    await db.execute(stmt)
    await db.commit()
