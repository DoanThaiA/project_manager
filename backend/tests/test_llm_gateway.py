"""AI Gateway: nhà cung cấp giả bằng httpx.MockTransport (không gọi Anthropic / OpenAI thật)."""

import json
from decimal import Decimal

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models import LlmProviderKey, LlmUsageLog
from app.services import llm_gateway as gw

ANTHROPIC_KEY = "sk-ant-real-key-0001"
OPENAI_KEY = "sk-openai-real-key-0002"
LLM = "http://test/llm"


def _sse(*events: dict) -> bytes:
    return b"".join(f"event: {e.get('type', 'message')}\ndata: {json.dumps(e)}\n\n".encode() for e in events)


def _upstream(request: httpx.Request) -> httpx.Response:
    """Nhà cung cấp giả: key chứa 'ratelimited' -> 429; còn lại trả lời theo đường dẫn + stream."""
    auth = request.headers.get("x-api-key") or request.headers.get("authorization", "")
    if "ratelimited" in auth:
        return httpx.Response(429, json={"error": "rate limited"})
    if request.method == "GET":
        return httpx.Response(200, json={"data": []})
    body = json.loads(request.content)
    if request.url.path == "/v1/messages":
        if body.get("stream"):
            events = _sse(
                {"type": "message_start", "message": {"usage": {"input_tokens": 10, "output_tokens": 1}}},
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Xin chào"}},
                {"type": "message_delta", "usage": {"output_tokens": 20}},
                {"type": "message_stop"},
            )
            return httpx.Response(200, content=events, headers={"content-type": "text/event-stream"})
        usage = {"input_tokens": 1000, "output_tokens": 500, "cache_read_input_tokens": 2000,
                 "cache_creation_input_tokens": 0}  # fmt: skip
        return httpx.Response(200, json={"id": "msg_1", "content": [{"type": "text", "text": "ok"}], "usage": usage})
    if request.url.path == "/v1/chat/completions":
        assert body.get("stream_options", {}).get("include_usage") is True  # gateway tự bật để đọc usage
        chunks = (
            b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
            b'data: {"choices":[],"usage":{"prompt_tokens":100,"completion_tokens":10,'
            b'"prompt_tokens_details":{"cached_tokens":40}}}\n\n'
            b"data: [DONE]\n\n"
        )
        return httpx.Response(200, content=chunks, headers={"content-type": "text/event-stream"})
    return httpx.Response(404, json={"error": "not found"})


@pytest.fixture(scope="module")
def upstream_calls():
    return []


@pytest.fixture(autouse=True)
def fake_upstream(monkeypatch, upstream_calls, gateway_key):
    from app.core.config import settings

    def handler(request: httpx.Request) -> httpx.Response:
        upstream_calls.append(request)
        return _upstream(request)

    monkeypatch.setattr(settings, "llm_encryption_key", gateway_key)
    monkeypatch.setattr(gw, "upstream_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(gw, "_client", None)


@pytest.fixture(scope="module")
def gateway_key():
    return Fernet.generate_key().decode()


@pytest.fixture(scope="module")
async def setup(client, login, project_id, gateway_key):
    from app.core.config import settings

    settings.llm_encryption_key = gateway_key  # fixture module chạy trước monkeypatch của từng test
    admin = await login("admin")
    for body in (
        {"provider": "anthropic", "name": "Anthropic chính", "api_key": ANTHROPIC_KEY},
        {"provider": "openai", "name": "OpenAI chính", "api_key": OPENAI_KEY},
    ):
        resp = await client.post("/llm/provider-keys", json=body, headers=admin)
        assert resp.status_code == 201, resp.text
    for body in (
        {"provider": "anthropic", "model": "claude-sonnet-5-5", "input_price": 3, "output_price": 15},
        {"provider": "anthropic", "model": "claude-haiku-5-5", "input_price": 1, "output_price": 5},
        {"provider": "openai", "model": "gpt-test", "input_price": 1, "output_price": 2, "cache_read_price": 0.5},
    ):
        assert (await client.post("/llm/models", json=body, headers=admin)).status_code == 201
    created = await client.post(
        "/llm/client-keys",
        json={"name": "ERP backend", "project_id": project_id, "allowed_models": ["claude-sonnet-5-5", "gpt-test"]},
        headers=admin,
    )
    assert created.status_code == 201, created.text
    return {"key": created.json()["key"], "id": created.json()["id"], "admin": admin}


async def _logs(client_key_id: int) -> list[LlmUsageLog]:
    async with AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(LlmUsageLog).where(LlmUsageLog.client_key_id == client_key_id).order_by(LlmUsageLog.id)
            )
        )


async def test_provider_key_is_never_returned(client, setup):
    listed = (await client.get("/llm/provider-keys", headers=setup["admin"])).json()
    assert {k["key_hint"] for k in listed} >= {"••••0001", "••••0002"}
    assert ANTHROPIC_KEY not in json.dumps(listed)
    async with AsyncSessionLocal() as db:
        stored = await db.scalar(select(LlmProviderKey.encrypted_key).where(LlmProviderKey.key_hint == "••••0001"))
    assert ANTHROPIC_KEY not in stored and gw.decrypt_key(stored) == ANTHROPIC_KEY


async def test_staff_cannot_manage_gateway(client, login, setup):
    staff = await login("dev.cuong")
    assert (await client.get("/llm/provider-keys", headers=staff)).status_code == 403
    assert (await client.post("/llm/client-keys", json={"name": "x"}, headers=staff)).status_code == 403


async def test_anthropic_messages_forwarded_with_real_key(client, setup, upstream_calls):
    upstream_calls.clear()
    resp = await client.post(
        f"{LLM}/anthropic/v1/messages",
        json={"model": "claude-sonnet-5-5", "max_tokens": 10, "messages": [{"role": "user", "content": "hi"}]},
        headers={"x-api-key": setup["key"], "anthropic-version": "2023-06-01"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == "msg_1"
    sent = upstream_calls[-1]
    assert sent.url == "https://api.anthropic.com/v1/messages"
    assert sent.headers["x-api-key"] == ANTHROPIC_KEY  # key thật, không lộ key dự án sang nhà cung cấp
    assert sent.headers["anthropic-version"] == "2023-06-01"

    log = (await _logs(setup["id"]))[-1]
    assert (log.input_tokens, log.output_tokens, log.cache_read_tokens) == (1000, 500, 2000)
    # 1000 x 3 + 500 x 15 + 2000 x 3 (giá cache bỏ trống = giá input) USD / 1 triệu token
    assert log.cost_usd == Decimal("0.016500")


async def test_anthropic_stream_passthrough_and_usage(client, setup):
    async with client.stream(
        "POST",
        f"{LLM}/anthropic/v1/messages",
        json={"model": "claude-sonnet-5-5", "max_tokens": 10, "stream": True, "messages": []},
        headers={"x-api-key": setup["key"]},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = b"".join([chunk async for chunk in resp.aiter_bytes()])
    assert b"Xin ch" in body and b"message_stop" in body
    log = (await _logs(setup["id"]))[-1]
    assert (log.stream, log.input_tokens, log.output_tokens) == (True, 10, 20)


async def test_openai_sdk_style_stream(client, setup, upstream_calls):
    async with client.stream(
        "POST",
        f"{LLM}/openai/v1/chat/completions",
        json={"model": "gpt-test", "stream": True, "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {setup['key']}"},
    ) as resp:
        assert resp.status_code == 200
        body = b"".join([chunk async for chunk in resp.aiter_bytes()])
    assert body.endswith(b"data: [DONE]\n\n")
    assert upstream_calls[-1].headers["authorization"] == f"Bearer {OPENAI_KEY}"
    log = (await _logs(setup["id"]))[-1]
    # prompt_tokens 100 gồm 40 token cache -> 60 input + 40 cache
    assert (log.input_tokens, log.cache_read_tokens, log.output_tokens) == (60, 40, 10)
    assert log.cost_usd == Decimal("0.000100")  # 60 x 1 + 40 x 0,5 + 10 x 2 = 100 / 1e6

    models = await client.get(f"{LLM}/openai/v1/models", headers={"Authorization": f"Bearer {setup['key']}"})
    assert [m["id"] for m in models.json()["data"]] == ["gpt-test"]


async def test_rejects_bad_keys_and_models(client, setup):
    url = f"{LLM}/anthropic/v1/messages"
    body = {"model": "claude-sonnet-5-5", "messages": []}
    resp = await client.post(url, json=body)
    assert resp.status_code == 401 and resp.json()["error"]["type"] == "authentication_error"
    assert (await client.post(url, json=body, headers={"x-api-key": "pm_llm_sai"})).status_code == 401

    headers = {"x-api-key": setup["key"]}
    off = await client.post(url, json={"model": "claude-chua-bat", "messages": []}, headers=headers)
    assert off.status_code == 400
    not_allowed = await client.post(url, json={"model": "claude-haiku-5-5", "messages": []}, headers=headers)
    assert not_allowed.status_code == 403 and not_allowed.json()["error"]["type"] == "permission_error"
    assert (await client.post(f"{LLM}/anthropic/v1/files", json={}, headers=headers)).status_code == 404


async def test_monthly_budget_blocks_requests(client, setup):
    admin = setup["admin"]
    keys = (await client.get("/llm/client-keys", headers=admin)).json()
    spent = next(k for k in keys if k["id"] == setup["id"])["spent_this_month"]
    assert spent > 0.0165

    await client.patch(f"/llm/client-keys/{setup['id']}", json={"monthly_budget_usd": 0.01}, headers=admin)
    resp = await client.post(
        f"{LLM}/anthropic/v1/messages",
        json={"model": "claude-sonnet-5-5", "messages": []},
        headers={"x-api-key": setup["key"]},
    )
    assert resp.status_code == 429 and "hạn mức" in resp.json()["error"]["message"]
    await client.patch(f"/llm/client-keys/{setup['id']}", json={"monthly_budget_usd": None}, headers=admin)

    summary = (await client.get("/llm/usage/summary", params={"month": _this_month()}, headers=admin)).json()
    row = next(r for r in summary["by_key"] if r["client_key_id"] == setup["id"])
    assert row["requests"] >= 3 and row["project"]["key"] == "ERP"
    assert {m["model"] for m in summary["by_model"]} >= {"claude-sonnet-5-5", "gpt-test"}


async def test_failover_to_next_key_on_rate_limit(client, setup, upstream_calls):
    admin = setup["admin"]
    bad = await client.post(
        "/llm/provider-keys",
        json={"provider": "anthropic", "name": "Key bị giới hạn", "api_key": "sk-ant-ratelimited-9999", "priority": 50},
        headers=admin,
    )
    upstream_calls.clear()
    resp = await client.post(
        f"{LLM}/anthropic/v1/messages",
        json={"model": "claude-sonnet-5-5", "messages": []},
        headers={"x-api-key": setup["key"]},
    )
    assert resp.status_code == 200, resp.text
    assert [r.headers["x-api-key"] for r in upstream_calls] == ["sk-ant-ratelimited-9999", ANTHROPIC_KEY]
    keys = {k["id"]: k for k in (await client.get("/llm/provider-keys", headers=admin)).json()}
    assert keys[bad.json()["id"]]["cooldown_until"] is not None  # key lỗi tạm nghỉ
    assert "429" in keys[bad.json()["id"]]["last_error"]
    await client.delete(f"/llm/provider-keys/{bad.json()['id']}", headers=admin)


async def test_revoked_key_stops_working(client, setup):
    admin = setup["admin"]
    created = await client.post("/llm/client-keys", json={"name": "Tạm"}, headers=admin)
    raw = created.json()["key"]
    assert raw.startswith("pm_llm_") and created.json()["key_prefix"].endswith("…")
    url = f"{LLM}/anthropic/v1/messages"
    body = {"model": "claude-haiku-5-5", "messages": []}
    assert (await client.post(url, json=body, headers={"x-api-key": raw})).status_code == 200
    await client.post(f"/llm/client-keys/{created.json()['id']}/revoke", headers=admin)
    assert (await client.post(url, json=body, headers={"x-api-key": raw})).status_code == 401


def _this_month() -> str:
    from app.api.llm_proxy import month_start

    return month_start().strftime("%Y-%m")
