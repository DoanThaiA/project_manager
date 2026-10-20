from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import Select, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ProjectMember


async def paginate(db: AsyncSession, stmt: Select, page: int, size: int) -> dict[str, Any]:
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = await db.execute(stmt.limit(size).offset((page - 1) * size))
    return {"items": rows.scalars().all(), "total": total or 0, "page": page, "size": size}


def not_found(what: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Không tìm thấy {what}")


def apply_update(obj: Any, data: BaseModel) -> dict[str, Any]:
    """Gán các trường client gửi lên (kể cả null), trả về dict đã gán."""
    values = data.model_dump(exclude_unset=True)
    for field, value in values.items():
        setattr(obj, field, value)
    return values


async def ensure_member(db: AsyncSession, project_id: int, user_id: int | None, field: str = "user") -> None:
    if user_id is None:
        return
    is_member = await db.scalar(
        select(exists().where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id))
    )
    if not is_member:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{field} (id={user_id}) không phải thành viên dự án",
        )
