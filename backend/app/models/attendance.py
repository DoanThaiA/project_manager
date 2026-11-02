from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import CIDR, INET
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AttendanceNetwork(TimestampMixin, Base):
    """IP / dải IP công cộng của văn phòng, được phép chấm công."""

    __tablename__ = "attendance_networks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    cidr: Mapped[str] = mapped_column(CIDR, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))


class AttendanceRecord(TimestampMixin, Base):
    """Bảng công: mỗi user một dòng mỗi ngày (giờ Việt Nam)."""

    __tablename__ = "attendance_records"
    __table_args__ = (UniqueConstraint("user_id", "work_date", name="uq_attendance_records_user_date"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    work_date: Mapped[date] = mapped_column(Date)
    check_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    check_in_ip: Mapped[str | None] = mapped_column(INET)
    check_in_network_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("attendance_networks.id", ondelete="SET NULL")
    )
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_out_ip: Mapped[str | None] = mapped_column(INET)
    check_out_network_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("attendance_networks.id", ondelete="SET NULL")
    )
    late_minutes: Mapped[int] = mapped_column(Integer, default=0)
    early_leave_minutes: Mapped[int] = mapped_column(Integer, default=0)
    worked_minutes: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(10), default="web")  # web | admin
    note: Mapped[str | None] = mapped_column(Text)
    adjusted_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    adjusted_reason: Mapped[str | None] = mapped_column(Text)


class AttendanceEvent(Base):
    """Một lần bấm check-in / check-out, kể cả bị từ chối."""

    __tablename__ = "attendance_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column(String(10))  # check_in | check_out
    accepted: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(String(30))  # outside_network | not_checked_in | api_token
    ip: Mapped[str | None] = mapped_column(INET)
    network_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("attendance_networks.id", ondelete="SET NULL")
    )
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
