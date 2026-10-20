from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import Permission, Project, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Không thể xác thực thông tin đăng nhập",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token)
    if payload is None or (sub := payload.get("sub")) is None:
        raise credentials_exception
    try:
        user_id = int(sub)
    except ValueError as exc:
        raise credentials_exception from exc

    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tài khoản đã bị khoá hoặc ngừng hoạt động")

    await set_audit_context(db, user.id, client_ip(request))
    return user


async def set_audit_context(db: AsyncSession, user_id: int, ip: str | None) -> None:
    """Ngữ cảnh audit: transaction hiện tại set ngay, các transaction sau do event after_begin set."""
    db.info["user_id"] = user_id
    db.info["client_ip"] = ip
    await db.execute(
        text("SELECT set_config('app.current_user_id', :uid, true), set_config('app.client_ip', :ip, true)"),
        {"uid": str(user_id), "ip": ip or ""},
    )


async def has_permission(db: AsyncSession, user: User, code: str, project_id: int | None = None) -> bool:
    if user.is_system_admin:
        return True
    return bool(await db.scalar(select(func.fn_user_has_permission(user.id, code, project_id))))


async def permission_codes(db: AsyncSession, user: User, project_id: int | None = None) -> list[str]:
    """Danh sách quyền của user (cấp hệ thống, hoặc trong một dự án)."""
    stmt = select(Permission.code).order_by(Permission.code)
    if not user.is_system_admin:
        stmt = stmt.where(func.fn_user_has_permission(user.id, Permission.code, project_id))
    return list((await db.scalars(stmt)).all())


def require_permission(code: str) -> Callable:
    """Quyền cấp hệ thống (qua user_roles)."""

    async def checker(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if not await has_permission(db, user, code):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Yêu cầu quyền '{code}'")
        return user

    return checker


@dataclass
class ProjectContext:
    user: User
    project: Project


def require_project_permission(code: str) -> Callable:
    """Quyền trong dự án (qua project_members), đọc project_id từ path.
    Vai trò hệ thống có cùng quyền (vd: SYSTEM_ADMIN) cũng được chấp nhận."""

    async def checker(
        project_id: int,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> ProjectContext:
        project = await db.get(Project, project_id)
        if project is None or project.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy dự án")
        if not await has_permission(db, user, code, project_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Yêu cầu quyền '{code}' trong dự án")
        return ProjectContext(user=user, project=project)

    return checker
