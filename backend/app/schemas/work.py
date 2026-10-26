from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import PriorityLevel, WorkActivityType, WorkItemStatus, WorkItemType
from app.schemas.common import ORMModel


class WorkItemCreate(BaseModel):
    type: WorkItemType = WorkItemType.task
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    acceptance_criteria: str | None = None
    status: WorkItemStatus | None = Field(default=None, description="Mặc định: todo nếu có sprint, ngược lại backlog")
    priority: PriorityLevel = PriorityLevel.medium
    story_points: Decimal | None = Field(default=None, ge=0)
    original_estimate_hours: Decimal | None = Field(default=None, ge=0)
    remaining_hours: Decimal | None = Field(default=None, ge=0)
    requirement_id: int | None = None
    sprint_id: int | None = None
    parent_id: int | None = None
    assignee_id: int | None = None
    backlog_rank: float | None = Field(default=None, description="Mặc định: cuối backlog")
    start_date: date | None = None
    due_date: date | None = None
    tags: list[str] = []


class WorkItemUpdate(BaseModel):
    type: WorkItemType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    acceptance_criteria: str | None = None
    status: WorkItemStatus | None = None
    priority: PriorityLevel | None = None
    story_points: Decimal | None = Field(default=None, ge=0)
    original_estimate_hours: Decimal | None = Field(default=None, ge=0)
    remaining_hours: Decimal | None = Field(default=None, ge=0)
    requirement_id: int | None = None
    sprint_id: int | None = None
    parent_id: int | None = None
    assignee_id: int | None = None
    backlog_rank: float | None = None
    start_date: date | None = None
    due_date: date | None = None
    tags: list[str] | None = None


class WorkItemOut(ORMModel):
    id: int
    project_id: int
    code: str
    type: WorkItemType
    title: str
    description: str | None
    acceptance_criteria: str | None
    status: WorkItemStatus
    priority: PriorityLevel
    story_points: Decimal | None
    original_estimate_hours: Decimal | None
    remaining_hours: Decimal | None
    requirement_id: int | None
    sprint_id: int | None
    parent_id: int | None
    assignee_id: int | None
    reporter_id: int | None
    backlog_rank: float
    start_date: date | None
    due_date: date | None
    completed_at: datetime | None
    tags: list[str]
    created_at: datetime
    updated_at: datetime
    subtask_count: int = 0
    subtask_done: int = 0


class WorkLogCreate(BaseModel):
    work_item_id: int | None = None
    requirement_id: int | None = None
    log_date: date = Field(default_factory=date.today)
    hours: Decimal = Field(gt=0, le=24)
    activity_type: WorkActivityType = WorkActivityType.development
    description: str = Field(min_length=1)
    is_billable: bool = True
    remaining_hours: Decimal | None = Field(
        default=None, ge=0, description="Cập nhật giờ còn lại của công việc; bỏ trống = tự trừ theo hours"
    )


class WorkLogUpdate(BaseModel):
    log_date: date | None = None
    hours: Decimal | None = Field(default=None, gt=0, le=24)
    activity_type: WorkActivityType | None = None
    description: str | None = Field(default=None, min_length=1)
    is_billable: bool | None = None


class WorkLogOut(ORMModel):
    id: int
    project_id: int
    user_id: int
    work_item_id: int | None
    requirement_id: int | None
    sprint_id: int | None
    log_date: date
    hours: Decimal
    activity_type: WorkActivityType
    description: str
    is_billable: bool
    created_at: datetime
    updated_at: datetime


class ActivityLogOut(ORMModel):
    id: int
    occurred_at: datetime
    actor_id: int | None
    actor_name: str | None = None
    project_id: int | None
    entity_type: str
    entity_id: int | None
    action: str
    old_values: dict[str, Any] | None
    new_values: dict[str, Any] | None
    ip_address: Any | None = None
    message: str | None


class WorkLogSummaryRow(BaseModel):
    key: str
    label: str | None
    total_hours: Decimal
    billable_hours: Decimal


class ProjectSummary(BaseModel):
    requirements_by_status: dict[str, int]
    requirements_overdue: int
    work_items_by_status: dict[str, int]
    total_logged_hours: Decimal
    budget_hours: Decimal | None
    active_sprint: dict[str, Any] | None
