import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ProjectContext, require_project_permission
from app.api.v1.endpoints.work_items import get_work_item
from app.core.config import settings
from app.db.session import get_db
from app.models import Attachment
from app.models.enums import AttachmentCategory
from app.schemas.attachment import AttachmentOut
from app.services import storage
from app.services.common import not_found

router = APIRouter()
logger = logging.getLogger(__name__)

ENTITY = "work_item"


def attachment_out(att: Attachment) -> AttachmentOut:
    fields = {name: getattr(att, name) for name in AttachmentOut.model_fields if name != "url"}
    return AttachmentOut(**fields, url=storage.image_url(att.storage_key))


async def read_image(file: UploadFile) -> tuple[bytes, str, str]:
    """Đọc file tải lên, kiểm tra dung lượng và đúng là ảnh; trả về (nội dung, mime, tên file)."""
    max_bytes = settings.attachment_max_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Ảnh vượt quá {settings.attachment_max_mb} MB")
    detected = storage.detect_image(data)
    if detected is None:
        raise HTTPException(status_code=422, detail="Chỉ nhận ảnh PNG, JPEG, GIF hoặc WebP")
    mime, ext = detected
    return data, mime, (file.filename or f"image.{ext}")[:255]


@router.get("/{item_id}/attachments", response_model=list[AttachmentOut], summary="Ảnh đính kèm của công việc")
async def list_attachments(
    item_id: int,
    ctx: ProjectContext = Depends(require_project_permission("work_item.view")),
    db: AsyncSession = Depends(get_db),
):
    await get_work_item(db, ctx.project.id, item_id)
    rows = await db.scalars(
        select(Attachment)
        .where(Attachment.entity_type == ENTITY, Attachment.entity_id == item_id)
        .order_by(Attachment.created_at, Attachment.id)
    )
    return [attachment_out(a) for a in rows]


@router.post(
    "/{item_id}/attachments",
    response_model=AttachmentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Tải ảnh lên Cloudflare Images (ảnh lỗi / ảnh kết quả)",
)
async def upload_attachment(
    item_id: int,
    file: UploadFile = File(...),
    category: AttachmentCategory = Form(...),
    ctx: ProjectContext = Depends(require_project_permission("work_item.update")),
    db: AsyncSession = Depends(get_db),
):
    await get_work_item(db, ctx.project.id, item_id)
    data, mime, file_name = await read_image(file)
    image_id = await storage.upload_image(
        data, file_name, mime, {"project_id": ctx.project.id, "work_item_id": item_id, "category": category}
    )
    att = Attachment(
        project_id=ctx.project.id,
        entity_type=ENTITY,
        entity_id=item_id,
        category=category,
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


@router.delete("/{item_id}/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Xoá ảnh")
async def delete_attachment(
    item_id: int,
    attachment_id: int,
    ctx: ProjectContext = Depends(require_project_permission("work_item.update")),
    db: AsyncSession = Depends(get_db),
):
    att = await db.get(Attachment, attachment_id)
    if att is None or att.project_id != ctx.project.id or att.entity_type != ENTITY or att.entity_id != item_id:
        raise not_found("ảnh đính kèm")
    image_id = att.storage_key
    await db.delete(att)
    await db.commit()
    try:
        await storage.delete_image(image_id)
    except Exception:  # đã xoá trong DB; ảnh sót trên Cloudflare không ảnh hưởng người dùng
        logger.exception("Không xoá được ảnh Cloudflare Images %s", image_id)
