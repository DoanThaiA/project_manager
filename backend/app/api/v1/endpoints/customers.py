from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.db.session import get_db
from app.models import Customer, CustomerContact, User
from app.models.enums import CustomerStatus
from app.schemas.common import Page
from app.schemas.customer import (
    ContactCreate,
    ContactOut,
    ContactUpdate,
    CustomerCreate,
    CustomerOut,
    CustomerUpdate,
)
from app.services.common import apply_update, not_found, paginate

router = APIRouter()


async def _get_customer(db: AsyncSession, customer_id: int) -> Customer:
    customer = await db.get(Customer, customer_id)
    if customer is None or customer.deleted_at is not None:
        raise not_found("khách hàng")
    return customer


async def _get_contact(db: AsyncSession, customer_id: int, contact_id: int) -> CustomerContact:
    contact = await db.get(CustomerContact, contact_id)
    if contact is None or contact.customer_id != customer_id:
        raise not_found("người liên hệ")
    return contact


async def _clear_primary(db: AsyncSession, customer_id: int, keep_id: int | None = None) -> None:
    stmt = update(CustomerContact).where(CustomerContact.customer_id == customer_id, CustomerContact.is_primary)
    if keep_id:
        stmt = stmt.where(CustomerContact.id != keep_id)
    await db.execute(stmt.values(is_primary=False))


@router.get("", response_model=Page[CustomerOut])
async def list_customers(
    q: str | None = Query(default=None, description="Tìm theo mã, tên, email"),
    status_: CustomerStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
    _: User = Depends(require_permission("customer.view")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Customer).where(Customer.deleted_at.is_(None)).order_by(Customer.name)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Customer.code.ilike(like), Customer.name.ilike(like), Customer.email.ilike(like)))
    if status_:
        stmt = stmt.where(Customer.status == status_)
    return await paginate(db, stmt, page, size)


@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
async def create_customer(
    body: CustomerCreate,
    user: User = Depends(require_permission("customer.create")),
    db: AsyncSession = Depends(get_db),
):
    customer = Customer(**body.model_dump(), created_by=user.id)
    db.add(customer)
    await db.commit()
    return customer


@router.get("/{customer_id}", response_model=CustomerOut)
async def get_customer(
    customer_id: int,
    _: User = Depends(require_permission("customer.view")),
    db: AsyncSession = Depends(get_db),
):
    return await _get_customer(db, customer_id)


@router.patch("/{customer_id}", response_model=CustomerOut)
async def update_customer(
    customer_id: int,
    body: CustomerUpdate,
    _: User = Depends(require_permission("customer.update")),
    db: AsyncSession = Depends(get_db),
):
    customer = await _get_customer(db, customer_id)
    apply_update(customer, body)
    await db.commit()
    return customer


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(
    customer_id: int,
    _: User = Depends(require_permission("customer.delete")),
    db: AsyncSession = Depends(get_db),
):
    customer = await _get_customer(db, customer_id)
    customer.deleted_at = func.now()
    await db.commit()


@router.get("/{customer_id}/contacts", response_model=list[ContactOut])
async def list_contacts(
    customer_id: int,
    _: User = Depends(require_permission("customer.view")),
    db: AsyncSession = Depends(get_db),
):
    await _get_customer(db, customer_id)
    stmt = (
        select(CustomerContact)
        .where(CustomerContact.customer_id == customer_id)
        .order_by(CustomerContact.is_primary.desc(), CustomerContact.full_name)
    )
    return (await db.scalars(stmt)).all()


@router.post("/{customer_id}/contacts", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
async def create_contact(
    customer_id: int,
    body: ContactCreate,
    _: User = Depends(require_permission("customer.update")),
    db: AsyncSession = Depends(get_db),
):
    await _get_customer(db, customer_id)
    if body.is_primary:
        await _clear_primary(db, customer_id)
    contact = CustomerContact(customer_id=customer_id, **body.model_dump())
    db.add(contact)
    await db.commit()
    return contact


@router.patch("/{customer_id}/contacts/{contact_id}", response_model=ContactOut)
async def update_contact(
    customer_id: int,
    contact_id: int,
    body: ContactUpdate,
    _: User = Depends(require_permission("customer.update")),
    db: AsyncSession = Depends(get_db),
):
    contact = await _get_contact(db, customer_id, contact_id)
    if body.is_primary:
        await _clear_primary(db, customer_id, keep_id=contact_id)
    apply_update(contact, body)
    await db.commit()
    return contact


@router.delete("/{customer_id}/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    customer_id: int,
    contact_id: int,
    _: User = Depends(require_permission("customer.update")),
    db: AsyncSession = Depends(get_db),
):
    contact = await _get_contact(db, customer_id, contact_id)
    await db.delete(contact)
    await db.commit()
