from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.enums import PriorityLevel, RequirementSource, RequirementStatus, RequirementType
from app.schemas.common import ORMModel


class RequirementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    acceptance_criteria: str | None = None
    type: RequirementType = RequirementType.feature
    source: RequirementSource = RequirementSource.email
    priority: PriorityLevel = PriorityLevel.medium
    business_value: int | None = Field(default=None, ge=1, le=100)
    estimated_hours: Decimal | None = Field(default=None, ge=0)
    received_at: datetime | None = None
    expected_date: date | None = None
    due_date: date | None = None
    target_release: str | None = Field(default=None, max_length=50)
    assignee_id: int | None = None
    customer_contact_id: int | None = None
    parent_id: int | None = None
    tags: list[str] = []


class RequirementUpdate(BaseModel):
    """Không cho đổi status ở đây — dùng POST /status để có kiểm tra luồng & quyền duyệt."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    acceptance_criteria: str | None = None
    type: RequirementType | None = None
    source: RequirementSource | None = None
    priority: PriorityLevel | None = None
    business_value: int | None = Field(default=None, ge=1, le=100)
    estimated_hours: Decimal | None = Field(default=None, ge=0)
    expected_date: date | None = None
    due_date: date | None = None
    target_release: str | None = Field(default=None, max_length=50)
    assignee_id: int | None = None
    customer_contact_id: int | None = None
    parent_id: int | None = None
    tags: list[str] | None = None


class RequirementStatusChange(BaseModel):
    status: RequirementStatus
    note: str | None = None
    rejected_reason: str | None = Field(default=None, description="Bắt buộc khi status = rejected")


class RequirementOut(ORMModel):
    id: int
    project_id: int
    code: str
    parent_id: int | None
    customer_id: int | None
    customer_contact_id: int | None
    title: str
    description: str | None
    acceptance_criteria: str | None
    type: RequirementType
    source: RequirementSource
    priority: PriorityLevel
    status: RequirementStatus
    business_value: int | None
    estimated_hours: Decimal | None
    received_at: datetime
    expected_date: date | None
    due_date: date | None
    target_release: str | None
    assignee_id: int | None
    approved_by: int | None
    approved_at: datetime | None
    rejected_reason: str | None
    resolved_at: datetime | None
    closed_at: datetime | None
    tags: list[str]
    created_by: int | None
    created_at: datetime
    updated_at: datetime


class RequirementStats(BaseModel):
    work_item_count: int
    work_item_done: int
    logged_hours: Decimal
    is_overdue: bool


class RequirementDetail(RequirementOut):
    stats: RequirementStats


class StatusHistoryOut(ORMModel):
    id: int
    from_status: RequirementStatus | None
    to_status: RequirementStatus
    changed_by: int | None
    changed_by_name: str | None = None
    note: str | None
    changed_at: datetime


class CommentCreate(BaseModel):
    content: str = Field(min_length=1)
    is_internal: bool = False
    parent_id: int | None = None


class CommentUpdate(BaseModel):
    content: str = Field(min_length=1)


class CommentOut(ORMModel):
    id: int
    requirement_id: int
    parent_id: int | None
    user_id: int | None
    user_name: str | None = None
    content: str
    is_internal: bool
    created_at: datetime
    updated_at: datetime
