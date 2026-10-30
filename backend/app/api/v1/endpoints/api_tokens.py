from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.security import hash_api_token, new_api_token
from app.db.session import get_db
from app.models import ApiToken, User
from app.schemas.api_token import ApiTokenCreate, ApiTokenCreated, ApiTokenOut

router = APIRouter()


@router.post(
    "/api-tokens", response_model=ApiTokenCreated, status_code=status.HTTP_201_CREATED, summary="Tạo token truy cập"
)
async def create_api_token(
    body: ApiTokenCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(UTC)
    token = new_api_token()
    row = ApiToken(
        user_id=user.id,
        name=body.name,
        token_hash=hash_api_token(token),
        expires_at=now + timedelta(days=body.expires_days),
    )
    db.add(row)
    await db.commit()
    return ApiTokenCreated(**ApiTokenOut.model_validate(row).model_dump(), token=token)


@router.get("/api-tokens", response_model=list[ApiTokenOut], summary="Danh sách token của tôi")
async def list_api_tokens(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.created_at.desc()))
    return [ApiTokenOut.model_validate(r) for r in rows]


@router.delete("/api-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Thu hồi token")
async def revoke_api_token(token_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        update(ApiToken)
        .where(ApiToken.id == token_id, ApiToken.user_id == user.id, ApiToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy token")
    await db.commit()
