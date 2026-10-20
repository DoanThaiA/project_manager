from datetime import date, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityLog, User
from app.schemas.work import ActivityLogOut


def activity_query(
    *,
    project_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    actor_id: int | None = None,
    action: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Select:
    stmt = (
        select(ActivityLog, User.full_name)
        .outerjoin(User, User.id == ActivityLog.actor_id)
        .order_by(ActivityLog.occurred_at.desc(), ActivityLog.id.desc())
    )
    if project_id is not None:
        stmt = stmt.where(ActivityLog.project_id == project_id)
    if entity_type:
        stmt = stmt.where(ActivityLog.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(ActivityLog.entity_id == entity_id)
    if actor_id is not None:
        stmt = stmt.where(ActivityLog.actor_id == actor_id)
    if action:
        stmt = stmt.where(ActivityLog.action == action)
    if date_from:
        stmt = stmt.where(ActivityLog.occurred_at >= date_from)
    if date_to:
        stmt = stmt.where(ActivityLog.occurred_at < date_to + timedelta(days=1))
    return stmt


async def fetch_activity(db: AsyncSession, stmt: Select, page: int, size: int) -> dict:
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = (await db.execute(stmt.limit(size).offset((page - 1) * size))).all()
    items = []
    for log, actor_name in rows:
        item = ActivityLogOut.model_validate(log)
        item.actor_name = actor_name
        item.ip_address = str(log.ip_address) if log.ip_address else None
        items.append(item)
    return {"items": items, "total": total or 0, "page": page, "size": size}
