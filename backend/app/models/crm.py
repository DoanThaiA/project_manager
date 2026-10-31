from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.enums import CrmContactStatus, CrmInquiryType


class CrmContact(TimestampMixin, Base):
    """Khách liên hệ của dự án (từ Gmail qua n8n, hoặc nhập tay) - không phải users / customers."""

    __tablename__ = "crm_contacts"
    __table_args__ = (UniqueConstraint("project_id", "email", name="uq_crm_contacts_project_email"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("projects.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(CITEXT)
    full_name: Mapped[str | None] = mapped_column(String(255))
    contact_email: Mapped[str | None] = mapped_column(CITEXT)
    phone: Mapped[str | None] = mapped_column(String(50))
    company: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)
    # varchar + CHECK (không phải ENUM PostgreSQL)
    status: Mapped[CrmContactStatus] = mapped_column(String(20), default=CrmContactStatus.new)
    assignee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30), default="gmail")
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))


class CrmEmailLead(Base):
    """Một email khách hỏi mua / báo giá / hỏi thông tin (n8n lọc từ Gmail, AI trích xuất)."""

    __tablename__ = "crm_email_leads"
    __table_args__ = (UniqueConstraint("project_id", "email_message_id", name="uq_crm_email_leads_message"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("projects.id", ondelete="CASCADE"))
    contact_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("crm_contacts.id", ondelete="CASCADE"))

    email_message_id: Mapped[str] = mapped_column(String(100))
    email_thread_id: Mapped[str | None] = mapped_column(String(100))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    subject: Mapped[str | None] = mapped_column(String(998))
    content: Mapped[str | None] = mapped_column(Text)

    customer_name: Mapped[str | None] = mapped_column(String(255))
    customer_email: Mapped[str] = mapped_column(CITEXT)
    contact_email: Mapped[str | None] = mapped_column(CITEXT)
    phone: Mapped[str | None] = mapped_column(String(50))
    company: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)

    inquiry_type: Mapped[CrmInquiryType] = mapped_column(String(20), default=CrmInquiryType.khac)
    product_type: Mapped[str | None] = mapped_column(String(255))
    quantity: Mapped[str | None] = mapped_column(String(255))
    specifications: Mapped[str | None] = mapped_column(Text)
    budget: Mapped[str | None] = mapped_column(String(255))
    deadline: Mapped[str | None] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text)
    ai_confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))

    source: Mapped[str] = mapped_column(String(30), default="gmail")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
