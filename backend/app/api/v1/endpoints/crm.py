"""CRM theo dự án: khách liên hệ qua Gmail (n8n gửi sang) + theo dõi trạng thái, người phụ trách."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ProjectContext, require_project_permission
from app.db.session import get_db
from app.models import CrmContact, CrmEmailLead
from app.models.enums import CrmContactStatus, CrmInquiryType
from app.schemas.common import Page
from app.schemas.crm import (
    CrmContactCreate,
    CrmContactOut,
    CrmContactUpdate,
    CrmEmailIngest,
    CrmEmailLeadOut,
    CrmIngestOut,
    CrmStats,
)
from app.services.common import apply_update, ensure_member, not_found, paginate

router = APIRouter()

CLOSED_STATUSES = (CrmContactStatus.won, CrmContactStatus.lost, CrmContactStatus.spam)
# Thông tin khách lấy từ email: chỉ điền vào các trường còn trống của crm_contacts, không ghi đè bản đã sửa tay
PROFILE_FIELDS = ("full_name", "contact_email", "phone", "company", "address")


def _contact_query(project_id: int) -> tuple[Select, dict]:
    """Khách liên hệ kèm số email, thời điểm & loại nhu cầu của email gần nhất."""
    stats = (
        select(
            CrmEmailLead.contact_id,
            func.count().label("email_count"),
            func.max(CrmEmailLead.received_at).label("last_contact_at"),
        )
        .where(CrmEmailLead.project_id == project_id)
        .group_by(CrmEmailLead.contact_id)
        .subquery()
    )
    latest = (
        select(CrmEmailLead.contact_id, CrmEmailLead.inquiry_type)
        .where(CrmEmailLead.project_id == project_id)
        .distinct(CrmEmailLead.contact_id)
        .order_by(CrmEmailLead.contact_id, CrmEmailLead.received_at.desc(), CrmEmailLead.id.desc())
        .subquery()
    )
    last_activity = func.coalesce(stats.c.last_contact_at, CrmContact.created_at)
    stmt = (
        select(CrmContact, func.coalesce(stats.c.email_count, 0), stats.c.last_contact_at, latest.c.inquiry_type)
        .outerjoin(stats, stats.c.contact_id == CrmContact.id)
        .outerjoin(latest, latest.c.contact_id == CrmContact.id)
        .where(CrmContact.project_id == project_id)
    )
    sorts = {
        "last_contact_at": last_activity,
        "created_at": CrmContact.created_at,
        "full_name": CrmContact.full_name,
        "email_count": func.coalesce(stats.c.email_count, 0),
    }
    return stmt, sorts


def _contact_out(row) -> CrmContactOut:
    contact, email_count, last_contact_at, last_inquiry_type = row
    return CrmContactOut.model_validate(
        {
            **CrmContactOut.model_validate(contact).model_dump(),
            "email_count": email_count,
            "last_contact_at": last_contact_at,
            "last_inquiry_type": last_inquiry_type,
        }
    )


async def _get_contact(db: AsyncSession, project_id: int, contact_id: int) -> CrmContact:
    contact = await db.get(CrmContact, contact_id)
    if contact is None or contact.project_id != project_id:
        raise not_found("khách liên hệ")
    return contact


async def _contact_detail(db: AsyncSession, project_id: int, contact_id: int) -> CrmContactOut:
    stmt, _ = _contact_query(project_id)
    row = (await db.execute(stmt.where(CrmContact.id == contact_id))).one_or_none()
    if row is None:
        raise not_found("khách liên hệ")
    return _contact_out(row)


async def _ensure_email_free(db: AsyncSession, project_id: int, email: str, exclude_id: int | None = None) -> None:
    # email là citext: so sánh không phân biệt hoa thường
    cond = [CrmContact.project_id == project_id, CrmContact.email == email]
    if exclude_id:
        cond.append(CrmContact.id != exclude_id)
    if await db.scalar(select(exists().where(*cond))):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Email {email} đã có trong CRM của dự án")


# ---------------------------------------------------------------- n8n


@router.post(
    "/emails/ingest",
    response_model=CrmIngestOut,
    summary="n8n gửi 1 email khách liên hệ (trùng email_message_id thì bỏ qua)",
    description=(
        "Gộp vào khách liên hệ theo `customer_email` (tạo mới nếu chưa có; chỉ điền các trường còn trống). "
        "Gọi bằng token truy cập (PAT) của tài khoản có quyền `crm.create` trong dự án."
    ),
)
async def ingest_email(
    body: CrmEmailIngest,
    ctx: ProjectContext = Depends(require_project_permission("crm.create")),
    db: AsyncSession = Depends(get_db),
):
    pid = ctx.project.id
    existing = (
        await db.execute(
            select(CrmEmailLead.id, CrmEmailLead.contact_id).where(
                CrmEmailLead.project_id == pid, CrmEmailLead.email_message_id == body.email_message_id
            )
        )
    ).first()
    if existing:
        return CrmIngestOut(lead_id=existing.id, contact_id=existing.contact_id, created=False)

    profile = {
        "full_name": body.customer_name,
        "contact_email": body.contact_email,
        "phone": body.phone,
        "company": body.company,
        "address": body.address,
    }
    upsert = pg_insert(CrmContact).values(
        project_id=pid, email=body.customer_email, source=body.source, created_by=ctx.user.id, **profile
    )
    columns = CrmContact.__table__.c
    upsert = upsert.on_conflict_do_update(
        constraint="uq_crm_contacts_project_email",
        set_={f: func.coalesce(columns[f], upsert.excluded[f]) for f in PROFILE_FIELDS},
    ).returning(CrmContact.id)
    contact_id = await db.scalar(upsert)

    insert_lead = (
        pg_insert(CrmEmailLead)
        .values(project_id=pid, contact_id=contact_id, **body.model_dump())
        .on_conflict_do_nothing(constraint="uq_crm_email_leads_message")
        .returning(CrmEmailLead.id)
    )
    lead_id = await db.scalar(insert_lead)
    created = lead_id is not None
    if not created:  # n8n gửi trùng cùng lúc: request kia đã ghi trước
        lead_id, contact_id = (
            await db.execute(
                select(CrmEmailLead.id, CrmEmailLead.contact_id).where(
                    CrmEmailLead.project_id == pid, CrmEmailLead.email_message_id == body.email_message_id
                )
            )
        ).one()
    await db.commit()
    return CrmIngestOut(lead_id=lead_id, contact_id=contact_id, created=created)


# ---------------------------------------------------------------- Thống kê


@router.get("/stats", response_model=CrmStats, summary="Số khách theo trạng thái, email 7 ngày qua")
async def crm_stats(
    ctx: ProjectContext = Depends(require_project_permission("crm.view")),
    db: AsyncSession = Depends(get_db),
):
    pid = ctx.project.id
    rows = await db.execute(
        select(CrmContact.status, func.count()).where(CrmContact.project_id == pid).group_by(CrmContact.status)
    )
    by_status = dict.fromkeys(CrmContactStatus, 0) | {CrmContactStatus(s): n for s, n in rows.all()}
    emails_7d = await db.scalar(
        select(func.count()).where(
            CrmEmailLead.project_id == pid, CrmEmailLead.received_at >= func.now() - timedelta(days=7)
        )
    )
    unassigned = await db.scalar(
        select(func.count()).where(
            CrmContact.project_id == pid,
            CrmContact.assignee_id.is_(None),
            CrmContact.status.not_in(CLOSED_STATUSES),
        )
    )
    return CrmStats(total=sum(by_status.values()), by_status=by_status, emails_7d=emails_7d, unassigned=unassigned)


# ---------------------------------------------------------------- Khách liên hệ


@router.get("/contacts", response_model=Page[CrmContactOut])
async def list_contacts(
    q: str | None = Query(default=None, description="Tìm theo email, tên, công ty, số điện thoại"),
    status_: list[CrmContactStatus] | None = Query(default=None, alias="status"),
    assignee_id: int | None = Query(default=None, description="0 = chưa có người phụ trách"),
    inquiry_type: CrmInquiryType | None = Query(default=None, description="Có email thuộc loại nhu cầu này"),
    sort: str = Query(default="-last_contact_at", description="Trường sắp xếp, tiền tố '-' = giảm dần"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=25, ge=1, le=200),
    ctx: ProjectContext = Depends(require_project_permission("crm.view")),
    db: AsyncSession = Depends(get_db),
):
    pid = ctx.project.id
    stmt, sorts = _contact_query(pid)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                CrmContact.email.ilike(like),
                CrmContact.full_name.ilike(like),
                CrmContact.company.ilike(like),
                CrmContact.phone.ilike(like),
            )
        )
    if status_:
        stmt = stmt.where(CrmContact.status.in_(status_))
    if assignee_id is not None:
        stmt = stmt.where(
            CrmContact.assignee_id.is_(None) if assignee_id == 0 else CrmContact.assignee_id == assignee_id
        )
    if inquiry_type:
        stmt = stmt.where(
            exists().where(CrmEmailLead.contact_id == CrmContact.id, CrmEmailLead.inquiry_type == inquiry_type)
        )
    column = sorts.get(sort.lstrip("-"))
    if column is None:
        raise HTTPException(status_code=422, detail=f"sort không hợp lệ, chọn một trong: {', '.join(sorts)}")
    order = column.desc().nulls_last() if sort.startswith("-") else column.asc().nulls_last()
    stmt = stmt.order_by(order, CrmContact.id.desc())

    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = await db.execute(stmt.limit(size).offset((page - 1) * size))
    return {"items": [_contact_out(r) for r in rows.all()], "total": total or 0, "page": page, "size": size}


@router.post("/contacts", response_model=CrmContactOut, status_code=status.HTTP_201_CREATED, summary="Thêm khách tay")
async def create_contact(
    body: CrmContactCreate,
    ctx: ProjectContext = Depends(require_project_permission("crm.create")),
    db: AsyncSession = Depends(get_db),
):
    pid = ctx.project.id
    await _ensure_email_free(db, pid, body.email)
    await ensure_member(db, pid, body.assignee_id, "Người phụ trách")
    contact = CrmContact(project_id=pid, source="manual", created_by=ctx.user.id, **body.model_dump())
    db.add(contact)
    await db.commit()
    return await _contact_detail(db, pid, contact.id)


@router.get("/contacts/{contact_id}", response_model=CrmContactOut)
async def get_contact(
    contact_id: int,
    ctx: ProjectContext = Depends(require_project_permission("crm.view")),
    db: AsyncSession = Depends(get_db),
):
    return await _contact_detail(db, ctx.project.id, contact_id)


@router.patch("/contacts/{contact_id}", response_model=CrmContactOut)
async def update_contact(
    contact_id: int,
    body: CrmContactUpdate,
    ctx: ProjectContext = Depends(require_project_permission("crm.update")),
    db: AsyncSession = Depends(get_db),
):
    pid = ctx.project.id
    contact = await _get_contact(db, pid, contact_id)
    values = body.model_dump(exclude_unset=True)
    for field, label in (("email", "Email"), ("status", "Trạng thái")):
        if field in values and values[field] is None:
            raise HTTPException(status_code=422, detail=f"{label} không được để trống")
    if values.get("email"):
        await _ensure_email_free(db, pid, values["email"], exclude_id=contact_id)
    await ensure_member(db, pid, values.get("assignee_id"), "Người phụ trách")
    apply_update(contact, body)
    await db.commit()
    return await _contact_detail(db, pid, contact_id)


@router.delete(
    "/contacts/{contact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Xoá khách liên hệ (kèm toàn bộ email của khách)",
)
async def delete_contact(
    contact_id: int,
    ctx: ProjectContext = Depends(require_project_permission("crm.delete")),
    db: AsyncSession = Depends(get_db),
):
    contact = await _get_contact(db, ctx.project.id, contact_id)
    await db.delete(contact)
    await db.commit()


# ---------------------------------------------------------------- Email


@router.get("/emails", response_model=Page[CrmEmailLeadOut])
async def list_emails(
    q: str | None = Query(default=None, description="Tìm theo tiêu đề, người gửi, công ty, tóm tắt"),
    contact_id: int | None = None,
    inquiry_type: CrmInquiryType | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=25, ge=1, le=200),
    ctx: ProjectContext = Depends(require_project_permission("crm.view")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(CrmEmailLead).where(CrmEmailLead.project_id == ctx.project.id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                CrmEmailLead.subject.ilike(like),
                CrmEmailLead.customer_email.ilike(like),
                CrmEmailLead.customer_name.ilike(like),
                CrmEmailLead.company.ilike(like),
                CrmEmailLead.summary.ilike(like),
            )
        )
    if contact_id is not None:
        stmt = stmt.where(CrmEmailLead.contact_id == contact_id)
    if inquiry_type:
        stmt = stmt.where(CrmEmailLead.inquiry_type == inquiry_type)
    if date_from:
        stmt = stmt.where(func.date(CrmEmailLead.received_at) >= date_from)
    if date_to:
        stmt = stmt.where(func.date(CrmEmailLead.received_at) <= date_to)
    stmt = stmt.order_by(CrmEmailLead.received_at.desc(), CrmEmailLead.id.desc())
    return await paginate(db, stmt, page, size)


@router.get("/emails/{lead_id}", response_model=CrmEmailLeadOut)
async def get_email(
    lead_id: int,
    ctx: ProjectContext = Depends(require_project_permission("crm.view")),
    db: AsyncSession = Depends(get_db),
):
    lead = await db.get(CrmEmailLead, lead_id)
    if lead is None or lead.project_id != ctx.project.id:
        raise not_found("email")
    return lead


@router.delete("/emails/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_email(
    lead_id: int,
    ctx: ProjectContext = Depends(require_project_permission("crm.delete")),
    db: AsyncSession = Depends(get_db),
):
    lead = await db.get(CrmEmailLead, lead_id)
    if lead is None or lead.project_id != ctx.project.id:
        raise not_found("email")
    await db.delete(lead)
    await db.commit()
