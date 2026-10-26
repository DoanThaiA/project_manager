"""File đính kèm (tài liệu, PDF, Excel, zip...) của công việc và yêu cầu, lưu trên MinIO (services/file_storage.py).

Ảnh lỗi / ảnh kết quả của công việc và ảnh dán trong văn bản vẫn ở Cloudflare Images (attachments.py).
"""

import logging
import mimetypes
import re
import uuid
from collections.abc import Awaitable, Callable
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ProjectContext, require_project_permission
from app.api.v1.endpoints.attachments import attachment_out
from app.api.v1.endpoints.requirements import get_requirement
from app.api.v1.endpoints.work_items import get_work_item
from app.core.config import settings
from app.db.session import get_db
from app.models import Attachment
from app.schemas.attachment import AttachmentOut
from app.services import file_storage
from app.services.common import not_found

logger = logging.getLogger(__name__)

STORAGE = "minio"
_EXT_RE = re.compile(r"^\.[a-z0-9]{1,10}$")


def _file_name(raw: str | None) -> str:
    # Chỉ lấy tên file, bỏ đường dẫn nếu trình duyệt gửi kèm (vd C:\Users\...\a.pdf)
    name = PurePosixPath((raw or "").replace("\\", "/")).name.strip()
    return name[:255] or "file"


def _object_key(project_id: int, entity: str, entity_id: int, file_name: str) -> str:
    ext = PurePosixPath(file_name).suffix.lower()
    return f"projects/{project_id}/{entity}/{entity_id}/{uuid.uuid4().hex}{ext if _EXT_RE.match(ext) else ''}"


def files_router(
    entity: str,
    get_entity: Callable[[AsyncSession, int, int], Awaitable[object]],
    view_permission: str,
    edit_permission: str,
) -> APIRouter:
    """Router /{entity_id}/files cho một loại bản ghi (attachments.entity_type = entity)."""
    router = APIRouter()

    async def _get_file(db: AsyncSession, project_id: int, entity_id: int, file_id: int) -> Attachment:
        att = await db.get(Attachment, file_id)
        if (
            att is None
            or att.project_id != project_id
            or att.entity_type != entity
            or att.entity_id != entity_id
            or att.storage != STORAGE
        ):
            raise not_found("file đính kèm")
        return att

    @router.get("/{entity_id}/files", response_model=list[AttachmentOut], summary="File đính kèm")
    async def list_files(
        entity_id: int,
        ctx: ProjectContext = Depends(require_project_permission(view_permission)),
        db: AsyncSession = Depends(get_db),
    ):
        await get_entity(db, ctx.project.id, entity_id)
        rows = await db.scalars(
            select(Attachment)
            .where(Attachment.entity_type == entity, Attachment.entity_id == entity_id, Attachment.storage == STORAGE)
            .order_by(Attachment.created_at, Attachment.id)
        )
        return [attachment_out(a) for a in rows]

    @router.post(
        "/{entity_id}/files",
        response_model=AttachmentOut,
        status_code=status.HTTP_201_CREATED,
        summary="Tải file đính kèm lên MinIO",
    )
    async def upload_file(
        entity_id: int,
        file: UploadFile = File(...),
        ctx: ProjectContext = Depends(require_project_permission(edit_permission)),
        db: AsyncSession = Depends(get_db),
    ):
        await get_entity(db, ctx.project.id, entity_id)
        size = file.size if file.size is not None else file.file.seek(0, 2)
        if size > settings.file_max_mb * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"File vượt quá {settings.file_max_mb} MB")
        if size == 0:
            raise HTTPException(status_code=422, detail="File rỗng")
        file_name = _file_name(file.filename)
        mime = file.content_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        key = _object_key(ctx.project.id, entity, entity_id, file_name)
        await file.seek(0)
        await file_storage.upload(key, file.file, size, mime)

        att = Attachment(
            project_id=ctx.project.id,
            entity_type=entity,
            entity_id=entity_id,
            file_name=file_name,
            storage=STORAGE,
            storage_key=key,
            mime_type=mime[:100],
            size_bytes=size,
            uploaded_by=ctx.user.id,
        )
        db.add(att)
        try:
            await db.commit()
        except Exception:
            await file_storage.delete(key)  # không để file mồ côi trên MinIO
            raise
        return attachment_out(att)

    @router.delete("/{entity_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Xoá file đính kèm")
    async def delete_file(
        entity_id: int,
        file_id: int,
        ctx: ProjectContext = Depends(require_project_permission(edit_permission)),
        db: AsyncSession = Depends(get_db),
    ):
        att = await _get_file(db, ctx.project.id, entity_id, file_id)
        key = att.storage_key
        await db.delete(att)
        await db.commit()
        try:
            await file_storage.delete(key)
        except Exception:  # đã xoá trong DB; file sót trên MinIO không ảnh hưởng người dùng
            logger.exception("Không xoá được file MinIO %s", key)

    return router


work_item_router = files_router("work_item", get_work_item, "work_item.view", "work_item.update")
requirement_router = files_router("requirement", get_requirement, "requirement.view", "requirement.update")
