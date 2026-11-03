"""Quản trị AI Gateway: key nhà cung cấp, model + giá, key dự án, thống kê sử dụng (docs/LLM_GATEWAY.md)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import cast, exists, func, select
from sqlalchemy.dialects.postgresql import DATE
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, require_permission
from app.api.llm_proxy import VN_TZ, month_start, spent_this_month
from app.core.config import settings
from app.db.session import get_db
from app.models import ActivityLog, LlmClientKey, LlmModel, LlmProvider, LlmProviderKey, LlmUsageLog, Project, User
from app.schemas.common import Page
from app.schemas.llm import (
    ClientKeyCreate,
    ClientKeyCreated,
    ClientKeyOut,
    ClientKeyUpdate,
    GatewayStatus,
    ModelIn,
    ModelOut,
    ProjectBrief,
    ProviderCreate,
    ProviderIn,
    ProviderKeyCreate,
    ProviderKeyOut,
    ProviderKeyTestOut,
    ProviderKeyUpdate,
    ProviderOut,
    UsageByDay,
    UsageByKey,
    UsageByModel,
    UsageLogOut,
    UsageSummary,
    UsageTotals,
)
from app.services import llm_gateway as gw
from app.services.common import not_found

router = APIRouter()

MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


def _encrypt(raw: str) -> str:
    try:
        return gw.encrypt_key(raw)
    except gw.GatewayDisabled as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


def _log(
    db: AsyncSession, request: Request, user: User, entity: str, entity_id: int, action: str, values: dict
) -> None:
    """Nhật ký thủ công (bảng key không gắn trigger audit để không chép key mã hoá vào nhật ký)."""
    db.add(
        ActivityLog(
            actor_id=user.id,
            entity_type=entity,
            entity_id=entity_id,
            action=action,
            new_values=values,
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    )


def _key_summary(pk: LlmProviderKey) -> dict:
    return {"provider": pk.provider, "name": pk.name, "key_hint": pk.key_hint}


@router.get("/status", response_model=GatewayStatus)
async def gateway_status(_: User = Depends(require_permission("llm.view"))):
    return GatewayStatus(enabled=gw.encryption_ready(), public_base_url=f"{settings.app_public_url.rstrip('/')}/llm")


# ---------------------------------------------------------------- Nhà cung cấp


async def _require_provider(db: AsyncSession, code: str) -> LlmProvider:
    prov = await db.scalar(select(LlmProvider).where(LlmProvider.code == code))
    if prov is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Chưa có nhà cung cấp '{code}'")
    return prov


async def _provider_out(db: AsyncSession, prov: LlmProvider) -> ProviderOut:
    keys = await db.scalar(select(func.count()).where(LlmProviderKey.provider == prov.code))
    models = await db.scalar(select(func.count()).where(LlmModel.provider == prov.code))
    return ProviderOut.model_validate(prov).model_copy(update={"key_count": keys or 0, "model_count": models or 0})


def _provider_values(body: ProviderIn) -> dict:
    return {**body.model_dump(), "base_url": str(body.base_url).rstrip("/")}


@router.get("/providers", response_model=list[ProviderOut], summary="Nhà cung cấp AI của gateway")
async def list_providers(
    _: User = Depends(require_permission("llm.view")),
    db: AsyncSession = Depends(get_db),
):
    providers = list(await db.scalars(select(LlmProvider).order_by(LlmProvider.is_builtin.desc(), LlmProvider.name)))
    return [await _provider_out(db, p) for p in providers]


@router.post("/providers", response_model=ProviderOut, status_code=status.HTTP_201_CREATED)
async def create_provider(
    body: ProviderCreate,
    _: User = Depends(require_permission("llm.manage")),
    db: AsyncSession = Depends(get_db),
):
    if await db.scalar(select(exists().where(LlmProvider.code == body.code))):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Đã có nhà cung cấp mã '{body.code}'")
    prov = LlmProvider(**_provider_values(body))
    db.add(prov)
    await db.commit()
    await db.refresh(prov)
    return await _provider_out(db, prov)


@router.put(
    "/providers/{code}",
    response_model=ProviderOut,
    summary="Sửa nhà cung cấp (gửi đủ trường; không đổi được mã)",
)
async def update_provider(
    code: str,
    body: ProviderIn,
    _: User = Depends(require_permission("llm.manage")),
    db: AsyncSession = Depends(get_db),
):
    prov = await _require_provider(db, code)
    if prov.is_builtin and body.api_format != prov.api_format:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Không đổi định dạng API của {prov.name}")
    for field, value in _provider_values(body).items():
        setattr(prov, field, value)
    await db.commit()
    await db.refresh(prov)
    return await _provider_out(db, prov)


@router.delete("/providers/{code}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    code: str,
    _: User = Depends(require_permission("llm.manage")),
    db: AsyncSession = Depends(get_db),
):
    prov = await _require_provider(db, code)
    if prov.is_builtin:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Không xoá được {prov.name} (có sẵn); có thể tắt")
    out = await _provider_out(db, prov)
    if out.key_count or out.model_count:
        raise HTTPException(status.HTTP_409_CONFLICT, "Xoá các key và model của nhà cung cấp này trước")
    await db.delete(prov)
    await db.commit()


# ---------------------------------------------------------------- Key nhà cung cấp


@router.get("/provider-keys", response_model=list[ProviderKeyOut])
async def list_provider_keys(
    _: User = Depends(require_permission("llm.manage")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(LlmProviderKey).order_by(LlmProviderKey.provider, LlmProviderKey.priority.desc(), LlmProviderKey.id)
    return list(await db.scalars(stmt))


@router.post("/provider-keys", response_model=ProviderKeyOut, status_code=status.HTTP_201_CREATED)
async def create_provider_key(
    body: ProviderKeyCreate,
    request: Request,
    user: User = Depends(require_permission("llm.manage")),
    db: AsyncSession = Depends(get_db),
):
    await _require_provider(db, body.provider)
    raw = body.api_key.strip()
    pk = LlmProviderKey(
        provider=body.provider,
        name=body.name,
        encrypted_key=_encrypt(raw),
        key_hint=gw.key_hint(raw),
        base_url=str(body.base_url).rstrip("/") if body.base_url else None,
        priority=body.priority,
        is_active=body.is_active,
        created_by=user.id,
    )
    db.add(pk)
    await db.flush()
    _log(db, request, user, "llm_provider_keys", pk.id, "create", _key_summary(pk))
    await db.commit()
    return pk


@router.patch("/provider-keys/{key_id}", response_model=ProviderKeyOut)
async def update_provider_key(
    key_id: int,
    body: ProviderKeyUpdate,
    request: Request,
    user: User = Depends(require_permission("llm.manage")),
    db: AsyncSession = Depends(get_db),
):
    pk = await db.get(LlmProviderKey, key_id)
    if pk is None:
        raise not_found("key nhà cung cấp")
    changes: dict[str, Any] = {}
    values = body.model_dump(exclude_unset=True, exclude={"api_key", "reset_cooldown"})
    if "base_url" in values:
        values["base_url"] = str(values["base_url"]).rstrip("/") if values["base_url"] else None
    for field, value in values.items():
        if value is not None or field == "base_url":
            setattr(pk, field, value)
            changes[field] = value
    if body.api_key:
        raw = body.api_key.strip()
        pk.encrypted_key, pk.key_hint = _encrypt(raw), gw.key_hint(raw)
        changes["key_hint"] = pk.key_hint
    if body.reset_cooldown or body.api_key:
        pk.cooldown_until = pk.last_error = pk.last_error_at = None
    _log(db, request, user, "llm_provider_keys", pk.id, "update", changes)
    await db.commit()
    await db.refresh(pk)
    return pk


@router.delete("/provider-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider_key(
    key_id: int,
    request: Request,
    user: User = Depends(require_permission("llm.manage")),
    db: AsyncSession = Depends(get_db),
):
    pk = await db.get(LlmProviderKey, key_id)
    if pk is None:
        raise not_found("key nhà cung cấp")
    _log(db, request, user, "llm_provider_keys", pk.id, "delete", _key_summary(pk))
    await db.delete(pk)
    await db.commit()


@router.post("/provider-keys/{key_id}/test", response_model=ProviderKeyTestOut, summary="Gọi thử danh sách model")
async def test_provider_key(
    key_id: int,
    _: User = Depends(require_permission("llm.manage")),
    db: AsyncSession = Depends(get_db),
):
    pk = await db.get(LlmProviderKey, key_id)
    if pk is None:
        raise not_found("key nhà cung cấp")
    try:
        raw = gw.decrypt_key(pk.encrypted_key)
    except gw.GatewayDisabled as exc:
        return ProviderKeyTestOut(ok=False, status_code=None, message=str(exc))
    prov = await db.scalar(select(LlmProvider).where(LlmProvider.code == pk.provider))
    headers = gw.upstream_headers(prov.api_format, raw, prov.extra_headers)
    if prov.api_format == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
    url = gw.upstream_url(pk.base_url or prov.base_url, "models")
    try:
        resp = await gw.upstream_client().get(url, headers=headers, timeout=20)
    except httpx.HTTPError as exc:
        return ProviderKeyTestOut(ok=False, status_code=None, message=f"Không kết nối được: {type(exc).__name__}")
    if resp.status_code == 200:
        pk.cooldown_until = pk.last_error = pk.last_error_at = None
        await db.commit()
        return ProviderKeyTestOut(ok=True, status_code=200, message="Key hoạt động")
    return ProviderKeyTestOut(ok=False, status_code=resp.status_code, message=resp.text[:500])


# ---------------------------------------------------------------- Model


@router.get("/models", response_model=list[ModelOut])
async def list_models(
    _: User = Depends(require_permission("llm.view")),
    db: AsyncSession = Depends(get_db),
):
    return list(await db.scalars(select(LlmModel).order_by(LlmModel.provider, LlmModel.model)))


async def _ensure_model_free(db: AsyncSession, provider: str, model: str, exclude_id: int | None = None) -> None:
    cond = [LlmModel.provider == provider, LlmModel.model == model]
    if exclude_id:
        cond.append(LlmModel.id != exclude_id)
    if await db.scalar(select(exists().where(*cond))):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Model {provider}/{model} đã có")


@router.post("/models", response_model=ModelOut, status_code=status.HTTP_201_CREATED)
async def create_model(
    body: ModelIn,
    _: User = Depends(require_permission("llm.manage")),
    db: AsyncSession = Depends(get_db),
):
    await _require_provider(db, body.provider)
    await _ensure_model_free(db, body.provider, body.model.strip())
    m = LlmModel(**{**body.model_dump(), "model": body.model.strip()})
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


@router.put("/models/{model_id}", response_model=ModelOut)
async def update_model(
    model_id: int,
    body: ModelIn,
    _: User = Depends(require_permission("llm.manage")),
    db: AsyncSession = Depends(get_db),
):
    m = await db.get(LlmModel, model_id)
    if m is None:
        raise not_found("model")
    await _require_provider(db, body.provider)
    await _ensure_model_free(db, body.provider, body.model.strip(), exclude_id=model_id)
    for field, value in {**body.model_dump(), "model": body.model.strip()}.items():
        setattr(m, field, value)
    await db.commit()
    await db.refresh(m)
    return m


@router.delete("/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    model_id: int,
    _: User = Depends(require_permission("llm.manage")),
    db: AsyncSession = Depends(get_db),
):
    m = await db.get(LlmModel, model_id)
    if m is None:
        raise not_found("model")
    await db.delete(m)
    await db.commit()


# ---------------------------------------------------------------- Key dự án


async def _projects(db: AsyncSession, ids: set[int | None]) -> dict[int, ProjectBrief]:
    ids.discard(None)
    if not ids:
        return {}
    rows = await db.scalars(select(Project).where(Project.id.in_(ids)))
    return {p.id: ProjectBrief.model_validate(p) for p in rows}


async def _client_key_out(
    db: AsyncSession, client_key: LlmClientKey, schema: type[ClientKeyOut] = ClientKeyOut, **extra
):
    """extra: trường thêm của schema, vd key= đầy đủ của ClientKeyCreated (nên tham số không tên 'key')."""
    projects = await _projects(db, {client_key.project_id})
    spent = await spent_this_month(db, client_key.id)
    return schema.model_validate(
        {
            **ClientKeyOut.model_validate(client_key).model_dump(),
            "project": projects.get(client_key.project_id),
            "spent_this_month": float(spent),
            **extra,
        }
    )


async def _check_project(db: AsyncSession, project_id: int | None) -> None:
    if project_id is not None:
        project = await db.get(Project, project_id)
        if project is None or project.deleted_at is not None:
            raise not_found("dự án")


@router.get("/client-keys", response_model=list[ClientKeyOut])
async def list_client_keys(
    _: User = Depends(require_permission("llm.view")),
    db: AsyncSession = Depends(get_db),
):
    keys = list(
        await db.scalars(
            select(LlmClientKey).order_by(LlmClientKey.revoked_at.is_not(None), LlmClientKey.created_at.desc())
        )
    )
    projects = await _projects(db, {k.project_id for k in keys})
    spent = dict(
        (
            await db.execute(
                select(LlmUsageLog.client_key_id, func.sum(LlmUsageLog.cost_usd))
                .where(LlmUsageLog.created_at >= month_start())
                .group_by(LlmUsageLog.client_key_id)
            )
        ).all()
    )
    return [
        ClientKeyOut.model_validate(k).model_copy(
            update={"project": projects.get(k.project_id), "spent_this_month": float(spent.get(k.id) or 0)}
        )
        for k in keys
    ]


@router.post(
    "/client-keys",
    response_model=ClientKeyCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Cấp key cho dự án (key đầy đủ chỉ trả về một lần)",
)
async def create_client_key(
    body: ClientKeyCreate,
    request: Request,
    user: User = Depends(require_permission("llm.manage")),
    db: AsyncSession = Depends(get_db),
):
    await _check_project(db, body.project_id)
    raw = gw.new_client_key()
    key = LlmClientKey(
        **body.model_dump(),
        key_hash=gw.hash_client_key(raw),
        key_prefix=raw[: len(gw.CLIENT_KEY_PREFIX) + 4] + "…",
        created_by=user.id,
    )
    db.add(key)
    await db.flush()
    summary = {"name": key.name, "project_id": key.project_id, "monthly_budget_usd": body.monthly_budget_usd}
    _log(db, request, user, "llm_client_keys", key.id, "create", summary)
    await db.commit()
    await db.refresh(key)
    return await _client_key_out(db, key, ClientKeyCreated, key=raw)


@router.patch("/client-keys/{key_id}", response_model=ClientKeyOut)
async def update_client_key(
    key_id: int,
    body: ClientKeyUpdate,
    request: Request,
    user: User = Depends(require_permission("llm.manage")),
    db: AsyncSession = Depends(get_db),
):
    key = await db.get(LlmClientKey, key_id)
    if key is None:
        raise not_found("key dự án")
    values = body.model_dump(exclude_unset=True)
    if "project_id" in values:
        await _check_project(db, values["project_id"])
    if values.get("name") is None:
        values.pop("name", None)
    if values.get("allowed_models") is None and "allowed_models" in values:
        values["allowed_models"] = []
    for field, value in values.items():
        setattr(key, field, value)
    _log(db, request, user, "llm_client_keys", key.id, "update", {k: str(v) for k, v in values.items()})
    await db.commit()
    await db.refresh(key)
    return await _client_key_out(db, key)


@router.post("/client-keys/{key_id}/revoke", response_model=ClientKeyOut, summary="Thu hồi key (không khôi phục)")
async def revoke_client_key(
    key_id: int,
    request: Request,
    user: User = Depends(require_permission("llm.manage")),
    db: AsyncSession = Depends(get_db),
):
    key = await db.get(LlmClientKey, key_id)
    if key is None:
        raise not_found("key dự án")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        _log(db, request, user, "llm_client_keys", key.id, "revoke", {"name": key.name})
        await db.commit()
        await db.refresh(key)
    return await _client_key_out(db, key)


@router.delete(
    "/client-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Xoá hẳn key đã thu hồi (lịch sử sử dụng giữ lại, hiện là key đã xoá)",
)
async def delete_client_key(
    key_id: int,
    request: Request,
    user: User = Depends(require_permission("llm.manage")),
    db: AsyncSession = Depends(get_db),
):
    key = await db.get(LlmClientKey, key_id)
    if key is None:
        raise not_found("key dự án")
    if key.revoked_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Thu hồi key trước khi xoá")
    _log(db, request, user, "llm_client_keys", key.id, "delete", {"name": key.name, "project_id": key.project_id})
    await db.delete(key)  # llm_usage_logs.client_key_id: ON DELETE SET NULL
    await db.commit()


# ---------------------------------------------------------------- Sử dụng


def _month_range(month: str) -> tuple[datetime, datetime]:
    start = datetime(int(month[:4]), int(month[5:7]), 1, tzinfo=VN_TZ)
    end = (start + timedelta(days=32)).replace(day=1)
    return start, end


def _totals_columns():
    return (
        func.count().label("requests"),
        func.count().filter(LlmUsageLog.status_code >= 400).label("errors"),
        func.coalesce(func.sum(LlmUsageLog.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(LlmUsageLog.output_tokens), 0).label("output_tokens"),
        func.coalesce(func.sum(LlmUsageLog.cache_read_tokens), 0).label("cache_read_tokens"),
        func.coalesce(func.sum(LlmUsageLog.cache_write_tokens), 0).label("cache_write_tokens"),
        func.coalesce(func.sum(LlmUsageLog.cost_usd), 0).label("cost_usd"),
    )


def _totals(row: Any) -> dict[str, Any]:
    return {
        "requests": row.requests,
        "errors": row.errors,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "cache_read_tokens": row.cache_read_tokens,
        "cache_write_tokens": row.cache_write_tokens,
        "cost_usd": float(row.cost_usd or Decimal(0)),
    }


@router.get("/usage/summary", response_model=UsageSummary, summary="Token + chi phí theo key dự án, model, ngày")
async def usage_summary(
    month: str = Query(pattern=MONTH_PATTERN, description="YYYY-MM"),
    _: User = Depends(require_permission("llm.view")),
    db: AsyncSession = Depends(get_db),
):
    start, end = _month_range(month)
    in_month = (LlmUsageLog.created_at >= start, LlmUsageLog.created_at < end)
    cols = _totals_columns()

    total = (await db.execute(select(*cols).where(*in_month))).one()

    key_rows = (
        await db.execute(
            select(LlmUsageLog.client_key_id, *cols)
            .where(*in_month)
            .group_by(LlmUsageLog.client_key_id)
            .order_by(func.sum(LlmUsageLog.cost_usd).desc())
        )
    ).all()
    keys = {
        k.id: k
        for k in await db.scalars(
            select(LlmClientKey).where(LlmClientKey.id.in_([r.client_key_id for r in key_rows if r.client_key_id]))
        )
    }
    projects = await _projects(db, {k.project_id for k in keys.values()})
    by_key = []
    for r in key_rows:
        k = keys.get(r.client_key_id)
        by_key.append(
            UsageByKey(
                client_key_id=r.client_key_id,
                name=k.name if k else None,
                project=projects.get(k.project_id) if k else None,
                monthly_budget_usd=float(k.monthly_budget_usd) if k and k.monthly_budget_usd is not None else None,
                **_totals(r),
            )
        )

    model_rows = (
        await db.execute(
            select(LlmUsageLog.provider, LlmUsageLog.model, *cols)
            .where(*in_month)
            .group_by(LlmUsageLog.provider, LlmUsageLog.model)
            .order_by(func.sum(LlmUsageLog.cost_usd).desc())
        )
    ).all()

    day = cast(func.timezone("Asia/Ho_Chi_Minh", LlmUsageLog.created_at), DATE).label("day")
    day_rows = (await db.execute(select(day, *cols).where(*in_month).group_by(day).order_by(day))).all()

    return UsageSummary(
        month=month,
        total=UsageTotals(**_totals(total)),
        by_key=by_key,
        by_model=[UsageByModel(provider=r.provider, model=r.model, **_totals(r)) for r in model_rows],
        by_day=[UsageByDay(date=r.day, **_totals(r)) for r in day_rows],
    )


@router.get("/usage/logs", response_model=Page[UsageLogOut], summary="Từng request qua gateway")
async def usage_logs(
    client_key_id: int | None = None,
    errors_only: bool = False,
    day: date | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    _: User = Depends(require_permission("llm.view")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(LlmUsageLog)
    if client_key_id:
        stmt = stmt.where(LlmUsageLog.client_key_id == client_key_id)
    if errors_only:
        stmt = stmt.where(LlmUsageLog.status_code >= 400)
    if day:
        start = datetime(day.year, day.month, day.day, tzinfo=VN_TZ)
        stmt = stmt.where(LlmUsageLog.created_at >= start, LlmUsageLog.created_at < start + timedelta(days=1))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    logs = list(await db.scalars(stmt.order_by(LlmUsageLog.id.desc()).limit(size).offset((page - 1) * size)))
    names = dict(
        (
            await db.execute(
                select(LlmClientKey.id, LlmClientKey.name).where(
                    LlmClientKey.id.in_({log.client_key_id for log in logs if log.client_key_id})
                )
            )
        ).all()
    )
    items = [
        UsageLogOut.model_validate(log).model_copy(update={"client_key_name": names.get(log.client_key_id)})
        for log in logs
    ]
    return {"items": items, "total": total or 0, "page": page, "size": size}
