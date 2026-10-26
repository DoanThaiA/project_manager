"""File đính kèm (tài liệu, PDF, Excel, zip...) lưu trên Cloudflare R2 (services/file_storage.py).

- Gắn với công việc / yêu cầu: /{id}/files
- Dán trong văn bản (yêu cầu, bình luận, log công việc, sprint review...): POST /inline-files, văn bản giữ dấu
  [File: <mã>/<tên file>]; tra URL theo tên qua GET /inline-images (dùng chung với ảnh dán trong văn bản).

Mỗi chỗ một folder trong bucket:
  projects/<project_id>/work-items/<id>/...      khu "File đính kèm" của công việc
  projects/<project_id>/requirements/<id>/...    khu "Tài liệu đính kèm" của yêu cầu
  projects/<project_id>/text/<nhóm>/...          file gắn trong ô văn bản, nhóm theo TextFileFolder

Ảnh lỗi / ảnh kết quả của công việc và ảnh dán trong văn bản vẫn ở Cloudflare Images (attachments.py).
"""

import logging
import mimetypes
import re
import uuid
from collections.abc import Awaitable, Callable
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ProjectContext, has_permission, require_project_permission
from app.api.v1.endpoints.attachments import attachment_out
from app.api.v1.endpoints.requirements import get_requirement
from app.api.v1.endpoints.work_items import get_work_item
from app.core.config import settings
from app.db.session import get_db
from app.models import Attachment
from app.models.enums import TextFileFolder
from app.schemas.attachment import AttachmentOut
from app.services import file_storage
from app.services.common import not_found

logger = logging.getLogger(__name__)

STORAGE = file_storage.STORAGE
_EXT_RE = re.compile(r"^\.[a-z0-9]{1,10}$")
# Tên file dán trong văn bản: mã ngẫu nhiên do client sinh + tên gốc; không chứa / \ ] hay xuống dòng
# để dấu [File: ...] nằm gọn trên một dòng
INLINE_NAME_RE = re.compile(r"^[0-9a-f]{16}/[^/\\\]\r\n]{1,200}$")


def _file_name(raw: str | None) -> str:
    # Chỉ lấy tên file, bỏ đường dẫn nếu trình duyệt gửi kèm (vd C:\Users\...\a.pdf)
    name = PurePosixPath((raw or "").replace("\\", "/")).name.strip()
    return name[:255] or "file"


def _object_key(project_id: int, folder: str, file_name: str) -> str:
    ext = PurePosixPath(file_name).suffix.lower()
    return f"projects/{project_id}/{folder}/{uuid.uuid4().hex}{ext if _EXT_RE.match(ext) else ''}"


async def save_file(
    db: AsyncSession,
    ctx: ProjectContext,
    file: UploadFile,
    entity: str,
    entity_id: int,
    file_name: str,
    folder: str,
) -> AttachmentOut:
    """Kiểm tra dung lượng, tải lên R2 vào projects/<id>/<folder>/ rồi lưu bản ghi attachments."""
    size = file.size if file.size is not None else file.file.seek(0, 2)
    if size > settings.file_max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File vượt quá {settings.file_max_mb} MB")
    if size == 0:
        raise HTTPException(status_code=422, detail="File rỗng")
    display = file_name.split("/", 1)[-1]
    mime = file.content_type or mimetypes.guess_type(display)[0] or "application/octet-stream"
    key = _object_key(ctx.project.id, folder, display)
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
        await file_storage.delete(key)  # không để file mồ côi trên R2
        raise
    return attachment_out(att)


def files_router(
    entity: str,
    get_entity: Callable[[AsyncSession, int, int], Awaitable[object]],
    view_permission: str,
    edit_permission: str,
    owner_field: str,
    folder: str,
) -> APIRouter:
    """Router /{entity_id}/files cho một loại bản ghi (attachments.entity_type = entity),
    file lưu ở projects/<project_id>/<folder>/<entity_id>/.

    Thêm / xoá file: người có quyền `edit_permission`, hoặc người tạo bản ghi (cột `owner_field`) — để
    khách hàng gửi được tài liệu kèm yêu cầu của mình (kể cả ngay lúc tạo) dù không có quyền sửa yêu cầu.
    """
    router = APIRouter()

    async def _check_edit(db: AsyncSession, ctx: ProjectContext, obj: object) -> None:
        if getattr(obj, owner_field) != ctx.user.id and not await has_permission(
            db, ctx.user, edit_permission, ctx.project.id
        ):
            raise HTTPException(status_code=403, detail=f"Yêu cầu quyền '{edit_permission}'")

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
        summary="Tải file đính kèm lên Cloudflare R2",
    )
    async def upload_file(
        entity_id: int,
        file: UploadFile = File(...),
        ctx: ProjectContext = Depends(require_project_permission(view_permission)),
        db: AsyncSession = Depends(get_db),
    ):
        await _check_edit(db, ctx, await get_entity(db, ctx.project.id, entity_id))
        return await save_file(db, ctx, file, entity, entity_id, _file_name(file.filename), f"{folder}/{entity_id}")

    @router.delete("/{entity_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Xoá file đính kèm")
    async def delete_file(
        entity_id: int,
        file_id: int,
        ctx: ProjectContext = Depends(require_project_permission(view_permission)),
        db: AsyncSession = Depends(get_db),
    ):
        await _check_edit(db, ctx, await get_entity(db, ctx.project.id, entity_id))
        att = await db.get(Attachment, file_id)
        if (
            att is None
            or att.project_id != ctx.project.id
            or att.entity_type != entity
            or att.entity_id != entity_id
            or att.storage != STORAGE
        ):
            raise not_found("file đính kèm")
        key = att.storage_key
        await db.delete(att)
        await db.commit()
        try:
            await file_storage.delete(key)
        except Exception:  # đã xoá trong DB; file sót trên R2 không ảnh hưởng người dùng
            logger.exception("Không xoá được file R2 %s", key)

    return router


work_item_router = files_router(
    "work_item", get_work_item, "work_item.view", "work_item.update", "reporter_id", "work-items"
)
requirement_router = files_router(
    "requirement", get_requirement, "requirement.view", "requirement.update", "created_by", "requirements"
)

inline_router = APIRouter()


@inline_router.post(
    "",
    response_model=AttachmentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Tải file dán trong văn bản lên Cloudflare R2",
)
async def upload_inline_file(
    file: UploadFile = File(...),
    name: str = Form(..., description="'<mã 16 hex>/<tên file>' — trùng với dấu [File: ...] trong văn bản"),
    folder: TextFileFolder = Form(TextFileFolder.other, description="Ô văn bản nào — mỗi nhóm một folder trên R2"),
    ctx: ProjectContext = Depends(require_project_permission("project.view")),
    db: AsyncSession = Depends(get_db),
):
    if not INLINE_NAME_RE.match(name):
        raise HTTPException(status_code=422, detail="Tên file không hợp lệ")
    # Gắn với dự án như ảnh dán trong văn bản: tải lên được cả khi bản ghi chứa văn bản chưa được tạo
    return await save_file(db, ctx, file, "inline", ctx.project.id, name, f"text/{folder.value}")
