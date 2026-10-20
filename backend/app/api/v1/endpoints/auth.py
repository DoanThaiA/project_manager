from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import client_ip, get_current_user, permission_codes, set_audit_context
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models import ActivityLog, User
from app.schemas.common import Message
from app.schemas.user import MeOut, PasswordChange, Token, UserDetail

router = APIRouter()


@router.post("/login", response_model=Token, summary="Đăng nhập bằng username hoặc email")
async def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> Token:
    user = await db.scalar(
        select(User).where(
            or_(User.username == form.username, User.email == form.username),
            User.deleted_at.is_(None),
        )
    )
    log = ActivityLog(
        actor_id=user.id if user else None,
        entity_type="users",
        entity_id=user.id if user else None,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    if user is None or not verify_password(form.password, user.password_hash):
        log.action, log.message = "login_failed", f"Đăng nhập thất bại: {form.username}"
        db.add(log)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sai tên đăng nhập hoặc mật khẩu",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tài khoản đã bị khoá hoặc ngừng hoạt động")

    log.action = "login"
    db.add(log)
    await set_audit_context(db, user.id, log.ip_address)
    user.last_login_at = func.now()
    await db.commit()
    return Token(access_token=create_access_token(str(user.id)))


@router.get("/me", response_model=MeOut, summary="Thông tin người dùng hiện tại + quyền hệ thống")
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> MeOut:
    loaded = await db.scalar(
        select(User)
        .options(selectinload(User.roles))
        .where(User.id == user.id)
        .execution_options(populate_existing=True)
    )
    detail = UserDetail.model_validate(loaded)
    return MeOut(**detail.model_dump(), permissions=await permission_codes(db, user))


@router.post("/change-password", response_model=Message)
async def change_password(
    body: PasswordChange,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Message:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mật khẩu hiện tại không đúng")
    user.password_hash = hash_password(body.new_password)
    await db.commit()
    return Message(detail="Đã đổi mật khẩu")
