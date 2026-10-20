from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, exists, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models import Permission, ProjectMember, Role, User, UserRole, role_permissions
from app.models.enums import RoleScope
from app.schemas.user import PermissionOut, RoleCreate, RoleDetail, RoleOut, RolePermissionsSet, RoleUpdate
from app.services.common import apply_update, not_found

router = APIRouter()


async def _load_role(db: AsyncSession, role_id: int) -> Role:
    role = await db.scalar(
        select(Role)
        .options(selectinload(Role.permissions))
        .where(Role.id == role_id)
        .execution_options(populate_existing=True)
    )
    if role is None:
        raise not_found("vai trò")
    return role


async def _set_permissions(db: AsyncSession, role_id: int, permission_ids: list[int]) -> None:
    permission_ids = list(dict.fromkeys(permission_ids))
    if permission_ids:
        found = set((await db.scalars(select(Permission.id).where(Permission.id.in_(permission_ids)))).all())
        if missing := set(permission_ids) - found:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Quyền không tồn tại: {sorted(missing)}"
            )
    await db.execute(delete(role_permissions).where(role_permissions.c.role_id == role_id))
    if permission_ids:
        await db.execute(
            insert(role_permissions), [{"role_id": role_id, "permission_id": pid} for pid in permission_ids]
        )


@router.get("/permissions", response_model=list[PermissionOut], summary="Danh mục chức năng")
async def list_permissions(_: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(Permission).order_by(Permission.module, Permission.code))).all()


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(
    scope: RoleScope | None = None,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Role).order_by(Role.scope, Role.id)
    if scope:
        stmt = stmt.where(Role.scope == scope)
    return (await db.scalars(stmt)).all()


@router.get("/roles/{role_id}", response_model=RoleDetail)
async def get_role(role_id: int, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _load_role(db, role_id)


@router.post("/roles", response_model=RoleDetail, status_code=status.HTTP_201_CREATED)
async def create_role(
    body: RoleCreate,
    _: User = Depends(require_permission("role.manage")),
    db: AsyncSession = Depends(get_db),
):
    role = Role(**body.model_dump(exclude={"permission_ids"}), is_builtin=False)
    db.add(role)
    await db.flush()
    await _set_permissions(db, role.id, body.permission_ids)
    await db.commit()
    return await _load_role(db, role.id)


@router.patch("/roles/{role_id}", response_model=RoleDetail)
async def update_role(
    role_id: int,
    body: RoleUpdate,
    _: User = Depends(require_permission("role.manage")),
    db: AsyncSession = Depends(get_db),
):
    role = await _load_role(db, role_id)
    apply_update(role, body)
    await db.commit()
    return await _load_role(db, role_id)


@router.put("/roles/{role_id}/permissions", response_model=RoleDetail, summary="Thay toàn bộ quyền của vai trò")
async def set_role_permissions(
    role_id: int,
    body: RolePermissionsSet,
    _: User = Depends(require_permission("role.manage")),
    db: AsyncSession = Depends(get_db),
):
    role = await _load_role(db, role_id)
    if role.code == "SYSTEM_ADMIN":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Không được sửa quyền SYSTEM_ADMIN")
    await _set_permissions(db, role_id, body.permission_ids)
    await db.commit()
    return await _load_role(db, role_id)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: int,
    _: User = Depends(require_permission("role.manage")),
    db: AsyncSession = Depends(get_db),
):
    role = await _load_role(db, role_id)
    if role.is_builtin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Không được xoá vai trò mặc định")
    in_use = await db.scalar(
        select(
            or_(
                exists().where(UserRole.role_id == role_id),
                exists().where(ProjectMember.role_id == role_id),
            )
        )
    )
    if in_use:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Vai trò đang được gán cho người dùng")
    await db.delete(role)
    await db.commit()
