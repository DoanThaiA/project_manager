"""AI Gateway: chuyển tiếp /llm/{code}/v1/... tới nhà cung cấp cấu hình trong llm_providers (docs/LLM_GATEWAY.md).

Dự án dùng SDK chính chủ, chỉ đổi base_url + api_key:
    Anthropic(base_url="https://<domain>/llm/anthropic", api_key="pm_llm_...")
    OpenAI(base_url="https://<domain>/llm/openai/v1", api_key="pm_llm_...")
    OpenAI(base_url="https://<domain>/llm/grok/v1", api_key="pm_llm_...")   # nhà cung cấp định dạng openai
Mount ngoài /api/v1 (main.py); nginx chuyển /llm/ thẳng tới API, tắt buffering để stream.
"""

import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import httpx
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal, get_db
from app.models import LlmClientKey, LlmModel, LlmProvider, LlmProviderKey, LlmUsageLog
from app.services import llm_gateway as gw

logger = logging.getLogger("app.llm_gateway")
router = APIRouter()

VN_TZ = timezone(timedelta(hours=7))
MAX_ATTEMPTS = 3  # số key thử tối đa cho một request
RETRYABLE = {429, 500, 502, 503, 504, 529}  # 529 = Anthropic quá tải
KEY_REJECTED = {401, 403}  # key nhà cung cấp sai / bị khoá: tạm nghỉ lâu hơn
FORWARD_HEADERS = ("content-type", "accept", "anthropic-version", "anthropic-beta", "openai-beta")
RESPONSE_HEADERS = ("request-id", "x-request-id", "openai-processing-ms", "retry-after")


def _error(api_format: str, status: int, message: str, kind: str) -> JSONResponse:
    """Lỗi theo định dạng API của nhà cung cấp để SDK hiển thị đúng."""
    if api_format == "anthropic":
        body = {"type": "error", "error": {"type": kind, "message": message}}
    else:
        body = {"error": {"message": message, "type": kind, "code": kind}}
    return JSONResponse(body, status_code=status)


def month_start() -> datetime:
    """Đầu tháng theo giờ Việt Nam: hạn mức tính theo tháng dương lịch."""
    now = datetime.now(VN_TZ)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def spent_this_month(db: AsyncSession, client_key_id: int) -> Decimal:
    return await db.scalar(
        select(func.coalesce(func.sum(LlmUsageLog.cost_usd), 0)).where(
            LlmUsageLog.client_key_id == client_key_id, LlmUsageLog.created_at >= month_start()
        )
    )


async def _authenticate(db: AsyncSession, request: Request) -> LlmClientKey | None:
    raw = gw.client_key_from_headers(request.headers)
    if not raw or not raw.startswith(gw.CLIENT_KEY_PREFIX):
        return None
    key = await db.scalar(select(LlmClientKey).where(LlmClientKey.key_hash == gw.hash_client_key(raw)))
    now = datetime.now(UTC)
    if key is None or key.revoked_at is not None or (key.expires_at and key.expires_at <= now):
        return None
    # Ghi last_used_at tối đa 1 lần / phút
    await db.execute(
        update(LlmClientKey)
        .where(
            LlmClientKey.id == key.id,
            or_(LlmClientKey.last_used_at.is_(None), LlmClientKey.last_used_at < now - timedelta(minutes=1)),
        )
        .values(last_used_at=func.now())
    )
    return key


async def _provider(db: AsyncSession, code: str) -> LlmProvider | None:
    return await db.scalar(select(LlmProvider).where(LlmProvider.code == code, LlmProvider.is_active))


async def _allowed_models(db: AsyncSession, provider: str, key: LlmClientKey) -> list[str]:
    stmt = select(LlmModel.model).where(LlmModel.provider == provider, LlmModel.is_active).order_by(LlmModel.model)
    models = list(await db.scalars(stmt))
    return [m for m in models if not key.allowed_models or m in key.allowed_models]


async def _provider_keys(db: AsyncSession, provider: str) -> list[LlmProviderKey]:
    """Key đang bật, không trong thời gian nghỉ; ưu tiên cao trước, lâu chưa dùng trước (xoay vòng)."""
    return list(
        await db.scalars(
            select(LlmProviderKey)
            .where(
                LlmProviderKey.provider == provider,
                LlmProviderKey.is_active,
                or_(LlmProviderKey.cooldown_until.is_(None), LlmProviderKey.cooldown_until <= func.now()),
            )
            .order_by(
                LlmProviderKey.priority.desc(),
                LlmProviderKey.last_used_at.asc().nulls_first(),
                LlmProviderKey.id,
            )
            .limit(MAX_ATTEMPTS)
        )
    )


async def _log_usage(
    *,
    key: LlmClientKey,
    provider: str,
    model: str | None,
    endpoint: str,
    provider_key_id: int | None,
    status_code: int,
    stream: bool,
    usage: gw.Usage,
    price: LlmModel | None,
    started: float,
    error: str | None = None,
) -> None:
    """Ghi bằng session riêng: request stream đã trả về trước khi đọc xong usage."""
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                LlmUsageLog(
                    client_key_id=key.id,
                    project_id=key.project_id,
                    provider=provider,
                    model=model,
                    endpoint=endpoint,
                    provider_key_id=provider_key_id,
                    status_code=status_code,
                    stream=stream,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_read_tokens=usage.cache_read_tokens,
                    cache_write_tokens=usage.cache_write_tokens,
                    cost_usd=gw.cost_usd(usage, price) if status_code < 400 else Decimal(0),
                    latency_ms=int((time.monotonic() - started) * 1000),
                    error=error[:1000] if error else None,
                )
            )
            await db.commit()
    except Exception:  # không để lỗi ghi log làm hỏng phản hồi
        logger.exception("Không ghi được llm_usage_logs")


def _cooldown(pk: LlmProviderKey, status: int | None, message: str) -> None:
    seconds = 600 if status in KEY_REJECTED else 60
    pk.cooldown_until = datetime.now(UTC) + timedelta(seconds=seconds)
    pk.last_error, pk.last_error_at = message[:1000], datetime.now(UTC)


@router.get("/{provider}/v1/models", summary="Model key này được dùng (định dạng của nhà cung cấp)")
async def list_models(provider: str, request: Request, db: AsyncSession = Depends(get_db)):
    prov = await _provider(db, provider)
    if prov is None:
        return _error("openai", 404, f"Gateway không có nhà cung cấp '{provider}'", "not_found_error")
    key = await _authenticate(db, request)
    if key is None:
        return _error(prov.api_format, 401, "Key gateway không hợp lệ, đã thu hồi hoặc hết hạn", "authentication_error")
    await db.commit()
    models = await _allowed_models(db, provider, key)
    if prov.api_format == "anthropic":
        data = [{"type": "model", "id": m, "display_name": m, "created_at": "1970-01-01T00:00:00Z"} for m in models]
        first, last = (models[0], models[-1]) if models else (None, None)
        return {"data": data, "has_more": False, "first_id": first, "last_id": last}
    return {
        "object": "list",
        "data": [{"id": m, "object": "model", "created": 0, "owned_by": provider} for m in models],
    }


@router.post("/{provider}/v1/{path:path}", summary="Chuyển tiếp request tới nhà cung cấp")
async def proxy(provider: str, path: str, request: Request, db: AsyncSession = Depends(get_db)):
    started = time.monotonic()
    prov = await _provider(db, provider)
    if prov is None:
        return _error("openai", 404, f"Gateway không có nhà cung cấp '{provider}'", "not_found_error")
    fmt = prov.api_format
    paths = gw.FORMAT_PATHS[fmt]
    if path not in paths:
        return _error(fmt, 404, f"Gateway không hỗ trợ /{provider}/v1/{path}", "not_found_error")
    billable = paths[path]

    key = await _authenticate(db, request)
    if key is None:
        return _error(fmt, 401, "Key gateway không hợp lệ, đã thu hồi hoặc hết hạn", "authentication_error")

    raw_body = await request.body()
    try:
        body = json.loads(raw_body) if raw_body else {}
    except ValueError:
        return _error(fmt, 400, "Body phải là JSON", "invalid_request_error")
    if not isinstance(body, dict):
        return _error(fmt, 400, "Body phải là JSON object", "invalid_request_error")
    model = body.get("model") if isinstance(body.get("model"), str) else None
    stream = body.get("stream") is True

    price: LlmModel | None = None
    if billable:
        price = await db.scalar(
            select(LlmModel).where(LlmModel.provider == provider, LlmModel.model == model, LlmModel.is_active)
        )
        if price is None:
            return _error(fmt, 400, f"Model '{model}' chưa được bật trên gateway", "invalid_request_error")
        if key.allowed_models and model not in key.allowed_models:
            return _error(fmt, 403, f"Key này không được dùng model '{model}'", "permission_error")
        if key.rpm_limit and not gw.rate_limiter.allow(key.id, key.rpm_limit):
            return _error(fmt, 429, f"Vượt giới hạn {key.rpm_limit} request / phút", "rate_limit_error")
        if key.monthly_budget_usd is not None:
            spent = await spent_this_month(db, key.id)
            if spent >= key.monthly_budget_usd:
                message = f"Đã dùng hết hạn mức tháng ({spent:.2f}/{key.monthly_budget_usd} USD)"
                return _error(fmt, 429, message, "rate_limit_error")
        # Định dạng OpenAI chỉ trả usage trong stream khi được yêu cầu (tắt được nếu nhà cung cấp không nhận tham số)
        if fmt == "openai" and prov.stream_usage and path in ("chat/completions", "completions") and stream:
            options = body.get("stream_options") if isinstance(body.get("stream_options"), dict) else {}
            body["stream_options"] = {**options, "include_usage": True}
            raw_body = json.dumps(body).encode()

    headers = {h: request.headers[h] for h in FORWARD_HEADERS if h in request.headers}
    if fmt == "anthropic":
        headers.setdefault("anthropic-version", "2023-06-01")
    headers.setdefault("content-type", "application/json")
    headers["accept-encoding"] = "identity"  # chuyển tiếp nguyên byte, không phải giải nén / nén lại

    candidates = await _provider_keys(db, provider)
    if not candidates:
        await db.commit()
        return _error(fmt, 503, f"Chưa có key {prov.name} nào sẵn sàng trên gateway", "overloaded_error")

    client = gw.upstream_client()
    upstream: httpx.Response | None = None
    used: LlmProviderKey | None = None
    last_error = "Không gọi được nhà cung cấp"
    for i, pk in enumerate(candidates):
        try:
            raw_key = gw.decrypt_key(pk.encrypted_key)
        except gw.GatewayDisabled as exc:
            await db.commit()
            return _error(fmt, 503, str(exc), "api_error")
        req = client.build_request(
            "POST",
            gw.upstream_url(pk.base_url or prov.base_url, path),
            params=request.query_params,
            content=raw_body,
            headers={**headers, **gw.upstream_headers(fmt, raw_key, prov.extra_headers)},
        )
        try:
            resp = await client.send(req, stream=True)
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            _cooldown(pk, None, last_error)
            continue
        is_last = i == len(candidates) - 1
        if (resp.status_code in RETRYABLE or resp.status_code in KEY_REJECTED) and not is_last:
            detail = (await resp.aread()).decode(errors="replace")
            await resp.aclose()
            _cooldown(pk, resp.status_code, f"HTTP {resp.status_code}: {detail}")
            continue
        upstream, used = resp, pk
        break

    if upstream is None or used is None:
        await db.commit()
        await _log_usage(
            key=key,
            provider=provider,
            model=model,
            endpoint=path,
            provider_key_id=None,
            status_code=502,
            stream=stream,
            usage=gw.Usage(),
            price=price,
            started=started,
            error=last_error,
        )
        return _error(fmt, 502, f"Không gọi được {prov.name}: {last_error}", "api_error")

    used.last_used_at = datetime.now(UTC)
    if upstream.status_code in RETRYABLE or upstream.status_code in KEY_REJECTED:
        _cooldown(used, upstream.status_code, f"HTTP {upstream.status_code}")
    await db.commit()

    out_headers = {h: upstream.headers[h] for h in RESPONSE_HEADERS if h in upstream.headers}
    content_type = upstream.headers.get("content-type", "application/json")
    log = {
        "key": key,
        "provider": provider,
        "model": model,
        "endpoint": path,
        "provider_key_id": used.id,
        "status_code": upstream.status_code,
        "stream": stream,
        "price": price,
        "started": started,
    }

    if "text/event-stream" not in content_type:
        data = await upstream.aread()
        await upstream.aclose()
        usage, error = gw.Usage(), None
        if upstream.status_code >= 400:
            error = data.decode(errors="replace")
        else:
            with contextlib.suppress(ValueError):
                usage = gw.usage_from_event(json.loads(data)) or gw.Usage()
        if billable:
            await _log_usage(**log, usage=usage, error=error)
        return Response(content=data, status_code=upstream.status_code, media_type=content_type, headers=out_headers)

    async def relay() -> AsyncIterator[bytes]:
        reader = gw.SseUsageReader()
        error = None
        try:
            async for chunk in upstream.aiter_bytes():
                reader.feed(chunk)
                yield chunk
        except Exception as exc:  # client ngắt kết nối / nhà cung cấp ngắt giữa chừng
            error = f"Stream bị ngắt: {type(exc).__name__}"
            raise
        finally:
            reader.close()
            await upstream.aclose()
            if billable:
                await _log_usage(**log, usage=reader.usage, error=error)

    return StreamingResponse(relay(), status_code=upstream.status_code, media_type=content_type, headers=out_headers)
