from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    FetchedValue,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB
from sqlalchemy.orm import Mapped, aliased, column_property, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, pg_enum
from app.models.enums import PriorityLevel, WorkActivityType, WorkItemStatus, WorkItemType


class WorkItem(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "work_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("projects.id", ondelete="CASCADE"))
    seq_no: Mapped[int] = mapped_column(Integer, server_default=FetchedValue())  # trigger sinh
    code: Mapped[str] = mapped_column(String(30), server_default=FetchedValue())  # trigger sinh
    type: Mapped[WorkItemType] = mapped_column(pg_enum(WorkItemType, "work_item_type"), default=WorkItemType.task)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    acceptance_criteria: Mapped[str | None] = mapped_column(Text)
    status: Mapped[WorkItemStatus] = mapped_column(
        pg_enum(WorkItemStatus, "work_item_status"), default=WorkItemStatus.backlog
    )
    priority: Mapped[PriorityLevel] = mapped_column(
        pg_enum(PriorityLevel, "priority_level"), default=PriorityLevel.medium
    )
    story_points: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    original_estimate_hours: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    remaining_hours: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    requirement_id: Mapped[int | None] = mapped_column(BigInteger)
    sprint_id: Mapped[int | None] = mapped_column(BigInteger)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("work_items.id"))
    assignee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    reporter_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    backlog_rank: Mapped[float] = mapped_column(Float, default=0)
    start_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)


# Số subtask (chưa xoá) và số subtask đã xong — để hiển thị tiến độ "2/5" trên board / backlog
_Subtask = aliased(WorkItem)
_subtasks = select(func.count(_Subtask.id)).where(_Subtask.parent_id == WorkItem.id, _Subtask.deleted_at.is_(None))
WorkItem.subtask_count = column_property(_subtasks.correlate_except(_Subtask).scalar_subquery())
WorkItem.subtask_done = column_property(
    _subtasks.where(_Subtask.status == WorkItemStatus.done).correlate_except(_Subtask).scalar_subquery()
)


class WorkLog(TimestampMixin, Base):
    __tablename__ = "work_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("projects.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    work_item_id: Mapped[int | None] = mapped_column(BigInteger)
    requirement_id: Mapped[int | None] = mapped_column(BigInteger)
    sprint_id: Mapped[int | None] = mapped_column(BigInteger)
    log_date: Mapped[date] = mapped_column(Date, server_default=func.current_date())
    hours: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    activity_type: Mapped[WorkActivityType] = mapped_column(
        pg_enum(WorkActivityType, "work_activity_type"), default=WorkActivityType.development
    )
    description: Mapped[str] = mapped_column(Text)
    is_billable: Mapped[bool] = mapped_column(Boolean, default=True)


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_id: Mapped[int | None] = mapped_column(BigInteger)
    project_id: Mapped[int | None] = mapped_column(BigInteger)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(30))
    old_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    new_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)
