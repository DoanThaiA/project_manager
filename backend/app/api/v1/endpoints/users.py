from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_permission
from app.core.security import hash_password
from app.db.session import get_db
from app.models import Role, User, UserRole
from app.models.enums import RoleScope, UserStatus
from app.schemas.common import Page
from app.schemas.user import PasswordReset, UserCreate, UserDetail, UserOut, UserRolesSet, UserUpdate
from app.services.common import apply_update, not_found, paginate

router = APIRouter()


async def _load_user(db: AsyncSession, user_id: int) -> User:
    user = await db.scalar(
        select(User)
        .options(selectinload(User.roles))
        .where(User.id == user_id, User.deleted_at.is_(None))
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise not_found("người dùng")
    return user


async def _set_system_roles(db: AsyncSession, user_id: int, role_ids: list[int], granted_by: int) -> None:
    role_ids = list(dict.fromkeys(role_ids))
    if role_ids:
        valid = set(
            (await db.scalars(select(Role.id).where(Role.id.in_(role_ids), Role.scope == RoleScope.system))).all()
        )
        if invalid := set(role_ids) - valid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Vai trò không tồn tại hoặc không phải vai trò hệ thống: {sorted(invalid)}",
            )
    await db.execute(delete(UserRole).where(UserRole.user_id == user_id))
    db.add_all(UserRole(user_id=user_id, role_id=rid, granted_by=granted_by) for rid in role_ids)


@router.get("", response_model=Page[UserOut])
async def list_users(
    q: str | None = Query(default=None, description="Tìm theo username, email, họ tên"),
    status_: UserStatus | None = Query(default=None, alias="status"),
    customer_id: int | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
    _: User = Depends(require_permission("user.view")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(User).where(User.deleted_at.is_(None)).order_by(User.full_name)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(User.username.ilike(like), User.email.ilike(like), User.full_name.ilike(like)))
    if status_:
        stmt = stmt.where(User.status == status_)
    if customer_id:
        stmt = stmt.where(User.customer_id == customer_id)
    return await paginate(db, stmt, page, size)


@router.post("", response_model=UserDetail, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    current: User = Depends(require_permission("user.create")),
    db: AsyncSession = Depends(get_db),
):
    if body.is_system_admin and not current.is_system_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Chỉ admin mới tạo được admin")
    user = User(
        **body.model_dump(exclude={"password", "role_ids"}),
        password_hash=hash_password(body.password),
    )
    db.add(user)
    await db.flush()
    await _set_system_roles(db, user.id, body.role_ids, current.id)
    await db.commit()
    return await _load_user(db, user.id)


@router.get("/{user_id}", response_model=UserDetail)
async def get_user(
    user_id: int,
    _: User = Depends(require_permission("user.view")),
    db: AsyncSession = Depends(get_db),
):
    return await _load_user(db, user_id)


@router.patch("/{user_id}", response_model=UserDetail)
async def update_user(
    user_id: int,
    body: UserUpdate,
    current: User = Depends(require_permission("user.update")),
    db: AsyncSession = Depends(get_db),
):
    user = await _load_user(db, user_id)
    if body.is_system_admin is not None and not current.is_system_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Chỉ admin mới đổi được quyền admin")
    apply_update(user, body)
    await db.commit()
    return await _load_user(db, user_id)


@router.put("/{user_id}/roles", response_model=UserDetail, summary="Gán vai trò hệ thống")
async def set_user_roles(
    user_id: int,
    body: UserRolesSet,
    current: User = Depends(require_permission("role.manage")),
    db: AsyncSession = Depends(get_db),
):
    await _load_user(db, user_id)
    await _set_system_roles(db, user_id, body.role_ids, current.id)
    await db.commit()
    return await _load_user(db, user_id)


async def _set_status(db: AsyncSession, user_id: int, current: User, new_status: UserStatus) -> User:
    if user_id == current.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Không thể tự khoá tài khoản của mình")
    user = await _load_user(db, user_id)
    user.status = new_status
    await db.commit()
    return user


@router.post("/{user_id}/lock", response_model=UserDetail)
async def lock_user(
    user_id: int,
    current: User = Depends(require_permission("user.lock")),
    db: AsyncSession = Depends(get_db),
):
    return await _set_status(db, user_id, current, UserStatus.locked)


@router.post("/{user_id}/unlock", response_model=UserDetail)
async def unlock_user(
    user_id: int,
    current: User = Depends(require_permission("user.lock")),
    db: AsyncSession = Depends(get_db),
):
    return await _set_status(db, user_id, current, UserStatus.active)


@router.post("/{user_id}/reset-password", response_model=UserOut)
async def reset_password(
    user_id: int,
    body: PasswordReset,
    _: User = Depends(require_permission("user.update")),
    db: AsyncSession = Depends(get_db),
):
    user = await _load_user(db, user_id)
    user.password_hash = hash_password(body.new_password)
    await db.commit()
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Xoá mềm người dùng")
async def delete_user(
    user_id: int,
    current: User = Depends(require_permission("user.lock")),
    db: AsyncSession = Depends(get_db),
):
    if user_id == current.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Không thể tự xoá tài khoản của mình")
    user = await _load_user(db, user_id)
    user.deleted_at = func.now()
    user.status = UserStatus.inactive
    await db.commit()
