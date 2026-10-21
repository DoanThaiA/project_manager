from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, FetchedValue, func
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Model ánh xạ vào schema do Alembic quản lý (backend/migrations), KHÔNG dùng metadata.create_all().
    Đổi model thì tạo migration: alembic revision --autogenerate -m "..." rồi đọc lại."""

    # Lấy giá trị do trigger sinh ra (code, seq_no, updated_at...) ngay qua RETURNING
    __mapper_args__ = {"eager_defaults": True}


def pg_enum(enum_cls: type[StrEnum], name: str) -> ENUM:
    """Kiểu ENUM đã tạo sẵn trong PostgreSQL."""
    return ENUM(enum_cls, name=name, create_type=False, values_callable=lambda e: [m.value for m in e])


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), server_onupdate=FetchedValue()
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
