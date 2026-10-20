from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import ProjectStatus, SprintStatus
from app.schemas.common import ORMModel
from app.schemas.user import RoleOut, UserBrief


class ProjectCreate(BaseModel):
    key: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,9}$", description="Tiền tố mã, vd: ERP")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    customer_id: int | None = None
    product_owner_id: int | None = Field(default=None, description="Mặc định: người tạo")
    scrum_master_id: int | None = None
    status: ProjectStatus = ProjectStatus.planning
    start_date: date | None = None
    end_date: date | None = None
    sprint_duration_days: int = Field(default=14, ge=1, le=60)
    budget_hours: Decimal | None = Field(default=None, ge=0)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    customer_id: int | None = None
    product_owner_id: int | None = None
    scrum_master_id: int | None = None
    status: ProjectStatus | None = None
    start_date: date | None = None
    end_date: date | None = None
    sprint_duration_days: int | None = Field(default=None, ge=1, le=60)
    budget_hours: Decimal | None = Field(default=None, ge=0)


class ProjectOut(ORMModel):
    id: int
    key: str
    name: str
    description: str | None
    customer_id: int | None
    product_owner_id: int | None
    scrum_master_id: int | None
    status: ProjectStatus
    start_date: date | None
    end_date: date | None
    sprint_duration_days: int
    budget_hours: Decimal | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime


class MemberAdd(BaseModel):
    user_id: int
    role_ids: list[int] = Field(min_length=1)


class MemberOut(BaseModel):
    user: UserBrief
    roles: list[RoleOut]
    joined_at: datetime


class SprintCreate(BaseModel):
    name: str | None = Field(default=None, max_length=150, description="Mặc định: 'Sprint <số>'")
    goal: str | None = None
    start_date: date
    end_date: date | None = Field(default=None, description="Mặc định: start_date + độ dài sprint của dự án")
    capacity_hours: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _check_dates(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date phải >= start_date")
        return self


class SprintUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    goal: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    capacity_hours: Decimal | None = Field(default=None, ge=0)
    review_note: str | None = None
    retrospective_note: str | None = None


class SprintComplete(BaseModel):
    move_unfinished_to: Literal["backlog", "next_sprint"] = "backlog"
    next_sprint_id: int | None = None
    review_note: str | None = None
    retrospective_note: str | None = None

    @model_validator(mode="after")
    def _check_next(self):
        if self.move_unfinished_to == "next_sprint" and self.next_sprint_id is None:
            raise ValueError("Cần next_sprint_id khi move_unfinished_to = next_sprint")
        return self


class SprintOut(ORMModel):
    id: int
    project_id: int
    sprint_no: int
    name: str
    goal: str | None
    start_date: date
    end_date: date
    status: SprintStatus
    capacity_hours: Decimal | None
    review_note: str | None
    retrospective_note: str | None
    created_at: datetime


class SprintProgress(BaseModel):
    sprint_id: int
    sprint_no: int
    name: str
    status: SprintStatus
    start_date: date
    end_date: date
    planned_points: Decimal
    completed_points: Decimal
    item_count: int
    done_count: int
    logged_hours: Decimal
