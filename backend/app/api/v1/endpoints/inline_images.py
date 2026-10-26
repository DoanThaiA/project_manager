"""Ảnh dán trong ô văn bản (mô tả yêu cầu, bình luận, log công việc, sprint review...).

Văn bản lưu dấu `[Ảnh: <tên file>]` mỗi dòng; tên file do client sinh ngẫu nhiên, duy nhất trong dự án.
Ảnh gắn với dự án (entity_type = 'inline', entity_id = project_id) nên tải lên được cả khi bản ghi
chứa văn bản chưa được tạo.

File (tài liệu, PDF...) dán trong văn bản tải lên qua /inline-files (Cloudflare R2), dấu [File: <mã>/<tên file>];
GET ở đây tra URL cho cả ảnh lẫn file theo tên.
"""

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ProjectContext, require_project_permission
from app.api.v1.endpoints.attachments import attachment_out, read_image
from app.db.session import get_db
from app.models import Attachment
from app.schemas.attachment import AttachmentOut
from app.services import storage

router = APIRouter()

ENTITY = "inline"


@router.get("", response_model=list[AttachmentOut], summary="Lấy URL các ảnh / file dán trong văn bản theo tên file")
async def resolve_inline_images(
    names: list[str] = Query(..., max_length=200),
    ctx: ProjectContext = Depends(require_project_permission("project.view")),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.scalars(
        select(Attachment)
        .where(
            Attachment.project_id == ctx.project.id,
            Attachment.entity_type == ENTITY,
            Attachment.file_name.in_(names),
        )
        .order_by(Attachment.id)
    )
    return [attachment_out(a) for a in rows]


@router.post(
    "",
    response_model=AttachmentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Tải ảnh dán trong văn bản lên Cloudflare Images",
)
async def upload_inline_image(
    file: UploadFile = File(...),
    ctx: ProjectContext = Depends(require_project_permission("project.view")),
    db: AsyncSession = Depends(get_db),
):
    data, mime, file_name = await read_image(file)
    image_id = await storage.upload_image(data, file_name, mime, {"project_id": ctx.project.id, "inline": True})
    att = Attachment(
        project_id=ctx.project.id,
        entity_type=ENTITY,
        entity_id=ctx.project.id,
        file_name=file_name,
        storage_key=image_id,
        mime_type=mime,
        size_bytes=len(data),
        uploaded_by=ctx.user.id,
    )
    db.add(att)
    try:
        await db.commit()
    except Exception:
        await storage.delete_image(image_id)  # không để ảnh mồ côi trên Cloudflare
        raise
    return attachment_out(att)
