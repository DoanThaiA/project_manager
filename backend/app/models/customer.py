from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, FetchedValue, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, pg_enum
from app.models.enums import CustomerStatus


class Customer(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    tax_code: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(CITEXT)
    phone: Mapped[str | None] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[CustomerStatus] = mapped_column(
        pg_enum(CustomerStatus, "customer_status"), default=CustomerStatus.active
    )
    note: Mapped[str | None] = mapped_column(Text)
    # users <-> customers tham chiếu vòng: use_alter để SQLAlchemy không cảnh báo khi sắp xếp bảng
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", use_alter=True))


class CustomerContact(Base):
    __tablename__ = "customer_contacts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("customers.id", ondelete="CASCADE"))
    full_name: Mapped[str] = mapped_column(String(150))
    position: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(CITEXT)
    phone: Mapped[str | None] = mapped_column(String(30))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), server_onupdate=FetchedValue()
    )
