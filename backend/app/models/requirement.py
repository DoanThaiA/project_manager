from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    FetchedValue,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, pg_enum
from app.models.enums import PriorityLevel, RequirementSource, RequirementStatus, RequirementType


class Requirement(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "requirements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("projects.id", ondelete="CASCADE"))
    seq_no: Mapped[int] = mapped_column(Integer, server_default=FetchedValue())  # trigger sinh
    code: Mapped[str] = mapped_column(String(30), server_default=FetchedValue())  # trigger sinh
    parent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("requirements.id"))
    customer_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("customers.id"))
    customer_contact_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("customer_contacts.id"))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    acceptance_criteria: Mapped[str | None] = mapped_column(Text)
    type: Mapped[RequirementType] = mapped_column(
        pg_enum(RequirementType, "requirement_type"), default=RequirementType.feature
    )
    source: Mapped[RequirementSource] = mapped_column(
        pg_enum(RequirementSource, "requirement_source"), default=RequirementSource.email
    )
    priority: Mapped[PriorityLevel] = mapped_column(
        pg_enum(PriorityLevel, "priority_level"), default=PriorityLevel.medium
    )
    status: Mapped[RequirementStatus] = mapped_column(
        pg_enum(RequirementStatus, "requirement_status"), default=RequirementStatus.new
    )
    business_value: Mapped[int | None] = mapped_column(SmallInteger)
    estimated_hours: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expected_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    target_release: Mapped[str | None] = mapped_column(String(50))
    assignee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_reason: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))


class RequirementComment(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "requirement_comments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    requirement_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("requirements.id", ondelete="CASCADE"))
    parent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("requirement_comments.id"))
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    content: Mapped[str] = mapped_column(Text)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False)


class RequirementStatusHistory(Base):
    __tablename__ = "requirement_status_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    requirement_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("requirements.id", ondelete="CASCADE"))
    from_status: Mapped[RequirementStatus | None] = mapped_column(pg_enum(RequirementStatus, "requirement_status"))
    to_status: Mapped[RequirementStatus] = mapped_column(pg_enum(RequirementStatus, "requirement_status"))
    changed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
