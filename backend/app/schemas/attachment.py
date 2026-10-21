from datetime import datetime

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
    url: str
