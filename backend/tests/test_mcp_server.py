from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from app.mcp_server import client as client_module
from app.mcp_server.client import PMClient, current_token
from app.mcp_server.http import ConnectorApp
from app.mcp_server.server import list_requirements, mcp, requirement_detail, sprint_progress


async def _always(_token: str) -> bool:
    return True


async def _never(_token: str) -> bool:
    return False


async def _call(app: ConnectorApp, path: str) -> tuple[int, bytes]:
    """Gọi ASGI trực tiếp, trả về (mã HTTP, nội dung)."""
    sent: list[dict[str, Any]] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "GET", "path": path, "raw_path": path.encode(), "headers": []}
    await app(scope, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, body


class FakeClient:
    """Thay PMClient.get: ghi lại đường dẫn và tham số, trả về dữ liệu cố định theo đường dẫn."""

    def __init__(self, responses: dict[str, Any]):
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def get(self, path: str, params: dict[str, Any] | None = None):
        self.calls.append((path, params))
        if path not in self.responses:
            raise ToolError(f"unexpected path {path}")
        return self.responses[path]


@pytest.fixture
def fake_api(monkeypatch):
    def install(responses: dict[str, Any]) -> FakeClient:
        fake = FakeClient(responses)
        monkeypatch.setattr(client_module.client, "get", fake.get)
        return fake

    return install


async def test_wrong_secret_returns_404_without_hint(monkeypatch):
    app = ConnectorApp(mcp, _never, rate_limit_per_minute=10)
    assert await _call(app, "/mcp/not-a-real-token") == (404, b"Not Found")
    assert await _call(app, "/mcp") == (404, b"Not Found")
    assert await _call(app, "/api/v1/auth/me") == (404, b"Not Found")


async def test_healthz_is_public():
    app = ConnectorApp(mcp, _never, rate_limit_per_minute=10)
    assert await _call(app, "/healthz") == (200, b"ok")


async def test_rate_limit_applies_per_connector():
    app = ConnectorApp(mcp, _always, rate_limit_per_minute=0)
    assert await _call(app, "/mcp/any-valid-looking-token") == (429, b"Too Many Requests")


async def test_token_validation_is_cached(monkeypatch):
    calls = 0

    class Resp:
        status_code = 200

    async def fake_get(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return Resp()

    pm = PMClient("http://unused")
    monkeypatch.setattr(pm._http, "get", fake_get)
    assert await pm.token_is_valid("pm_pat_x")
    assert await pm.token_is_valid("pm_pat_x")
    assert calls == 1


async def test_tool_sends_token_and_clamps_limit(fake_api):
    fake = fake_api({"/projects/1/requirements": {"total": 3, "items": [{"code": "ERP-REQ-1"}]}})
    token = current_token.set("pm_pat_test")
    try:
        result = await list_requirements(project_id=1, overdue=True, limit=500)
    finally:
        current_token.reset(token)

    assert result == {"total": 3, "items": [{"code": "ERP-REQ-1"}]}
    path, params = fake.calls[0]
    assert path == "/projects/1/requirements"
    assert params["overdue"] is True
    assert params["size"] == 50  # limit bị giới hạn ở 50 (None được bỏ ở PMClient.get, xem test_clean_params)


async def test_sprint_progress_defaults_to_active_sprint(fake_api):
    fake = fake_api(
        {
            "/projects/1/sprints": [{"id": 7}],
            "/projects/1/sprints/7/progress": {"sprint_id": 7},
        }
    )
    assert await sprint_progress(project_id=1) == {"sprint_id": 7}
    assert fake.calls[0] == ("/projects/1/sprints", {"status": "active"})


async def test_sprint_progress_without_active_sprint_is_clear_error(fake_api):
    fake_api({"/projects/1/sprints": []})
    with pytest.raises(ToolError, match="không có sprint đang chạy"):
        await sprint_progress(project_id=1)


async def test_requirement_detail_combines_three_reads(fake_api):
    base = "/projects/1/requirements/5"
    fake = fake_api(
        {
            base: {"code": "ERP-REQ-0005"},
            f"{base}/history": [{"to_status": "approved"}],
            f"{base}/comments": [{"id": i} for i in range(40)],
        }
    )
    result = await requirement_detail(project_id=1, requirement_id=5)
    assert result["detail"] == {"code": "ERP-REQ-0005"}
    assert result["history"] == [{"to_status": "approved"}]
    assert len(result["comments"]) == 30  # 30 bình luận gần nhất
    assert {path for path, _ in fake.calls} == {base, f"{base}/history", f"{base}/comments"}


def test_clean_params_drops_none():
    from app.mcp_server.client import _clean

    assert _clean({"a": None, "b": 1, "c": False}) == {"b": 1, "c": False}


def test_error_message_maps_status_codes():
    import httpx

    from app.mcp_server.client import _error_message

    assert "Không có quyền" in _error_message(httpx.Response(403, json={"detail": "x"}))
    body = {"detail": [{"msg": "Input should be a valid date"}]}
    assert "valid date" in _error_message(httpx.Response(422, json=body))
