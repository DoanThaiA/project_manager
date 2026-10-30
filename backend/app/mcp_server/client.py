"""Gọi REST API nội bộ với token của connector. Mọi quyền do API kiểm tra, MCP không đọc DB trực tiếp."""

import time
from contextvars import ContextVar
from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from app.core.config import settings
from app.core.security import hash_api_token

# Token của request hiện tại, đặt bởi lớp HTTP (http.py) trước khi tool chạy
current_token: ContextVar[str | None] = ContextVar("mcp_token", default=None)

_ERRORS = {
    401: "Token không hợp lệ hoặc đã hết hạn",
    403: "Không có quyền xem dữ liệu này",
    404: "Không tìm thấy dữ liệu (kiểm tra lại mã dự án, yêu cầu hoặc sprint)",
}


def _clean(params: dict[str, Any] | None) -> dict[str, Any]:
    """Bỏ tham số None để không gửi lên API."""
    return {k: v for k, v in (params or {}).items() if v is not None}


def _error_message(resp: httpx.Response) -> str:
    if resp.status_code in _ERRORS:
        return _ERRORS[resp.status_code]
    try:
        detail = resp.json().get("detail")
    except ValueError:
        detail = None
    if isinstance(detail, list):  # lỗi kiểu dữ liệu của FastAPI
        detail = "; ".join(str(d.get("msg", d)) for d in detail)
    return f"Lỗi từ hệ thống ({resp.status_code}): {detail or 'không rõ'}"


class PMClient:
    def __init__(self, base_url: str) -> None:
        self._http = httpx.AsyncClient(base_url=base_url, timeout=20)
        self._valid: dict[str, float] = {}  # hash token -> thời điểm hết cache

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        token = current_token.get()
        if token is None:
            raise ToolError("Thiếu token truy cập")
        resp = await self._http.get(path, params=_clean(params), headers={"Authorization": f"Bearer {token}"})
        if resp.status_code >= 400:
            raise ToolError(_error_message(resp))
        return resp.json()

    async def token_is_valid(self, token: str) -> bool:
        """Kiểm tra token qua /auth/me. Kết quả hợp lệ được cache ngắn để giảm số lần gọi API."""
        key = hash_api_token(token)
        now = time.monotonic()
        if self._valid.get(key, 0) > now:
            return True
        resp = await self._http.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        if resp.status_code != 200:
            self._valid.pop(key, None)
            return False
        self._valid[key] = now + settings.mcp_token_cache_seconds
        return True

    async def aclose(self) -> None:
        await self._http.aclose()


client = PMClient(settings.mcp_api_url)
