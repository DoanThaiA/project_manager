from datetime import datetime
from typing import Literal

from app.models.enums import AttachmentCategory
from app.schemas.common import ORMModel


class AttachmentOut(ORMModel):
    id: int
    entity_id: int
    category: AttachmentCategory | None
    file_name: str
    mime_type: str | None
    size_bytes: int | None
    uploaded_by: int | None
    created_at: datetime
    url: str  # file trên R2: link tải về (attachment); ảnh: link hiển thị
    # Xem trực tiếp trên trình duyệt (chỉ file trên R2): pdf / ảnh / video / audio / văn bản hiển thị thẳng
    # preview_url; office (Word, Excel, PowerPoint) mở qua Office Online; None = chỉ tải về được
    preview_kind: Literal["pdf", "image", "video", "audio", "text", "office"] | None = None
    preview_url: str | None = None
