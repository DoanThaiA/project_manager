"""Lớp HTTP cho connector URL: https://<domain>/mcp/<token>.

Token nằm trong đường dẫn vì connector không gửi được header xác thực. Token sai hoặc hết hạn trả 404,
không để lộ đây là endpoint MCP. Đường dẫn chứa bí mật nên không được ghi vào log truy cập (xem __main__.py).
"""

import re
import time
from collections import deque
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from urllib.parse import urlparse

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from app.core.config import settings
from app.core.security import hash_api_token
from app.mcp_server.client import client, current_token
from app.mcp_server.server import mcp

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]

SECRET_PATH = re.compile(r"^/mcp/([^/]+)/?$")
NOT_FOUND = b"Not Found"
WINDOW_SECONDS = 60


async def _respond(send: Send, status: int, body: bytes, extra: list[tuple[bytes, bytes]] | None = None) -> None:
    headers = [(b"content-type", b"text/plain; charset=utf-8"), (b"content-length", str(len(body)).encode())]
    await send({"type": "http.response.start", "status": status, "headers": headers + (extra or [])})
    await send({"type": "http.response.body", "body": body})


class ConnectorApp:
    """ASGI: kiểm tra token trong đường dẫn, giới hạn tần suất theo token, rồi chuyển cho MCP (stateless)."""

    def __init__(
        self,
        server: MCPServer[Any],
        validate: Callable[[str], Awaitable[bool]],
        rate_limit_per_minute: int,
        public_host: str,
    ) -> None:
        # Host header là domain công khai (nginx truyền $host) hoặc localhost khi chạy thử.
        # Không có host này SDK từ chối request với 421 "Invalid Host header".
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[public_host, "localhost:*", "127.0.0.1:*"],
            allowed_origins=[f"https://{public_host}", "http://localhost:*", "http://127.0.0.1:*"],
        )
        self._inner = server.streamable_http_app(
            streamable_http_path="/mcp",
            stateless_http=True,
            json_response=True,
            transport_security=security,
        )
        self._validate = validate
        self._limit = rate_limit_per_minute
        self._hits: dict[str, deque[float]] = {}

    def _allow(self, key: str) -> bool:
        now = time.monotonic()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] > WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":  # khởi động/tắt session manager của MCP
            await self._inner(scope, receive, send)
            return
        if scope["type"] != "http":
            return
        if scope["path"] == "/healthz":
            await _respond(send, 200, b"ok")
            return

        match = SECRET_PATH.match(scope["path"])
        if match is None:
            await _respond(send, 404, NOT_FOUND)
            return
        token = match.group(1)
        if not await self._validate(token):
            await _respond(send, 404, NOT_FOUND)
            return
        if scope["method"] == "GET":
            # Server không gửi thông báo chủ động tới client, nên không mở luồng SSE (luồng này sẽ bị proxy cắt).
            # MCP spec cho phép trả 405 trong trường hợp này.
            await _respond(send, 405, b"Method Not Allowed", [(b"allow", b"POST, DELETE")])
            return
        if not self._allow(hash_api_token(token)):
            await _respond(send, 429, b"Too Many Requests")
            return

        reset = current_token.set(token)
        try:
            await self._inner({**scope, "path": "/mcp", "raw_path": b"/mcp"}, receive, send)
        finally:
            current_token.reset(reset)


def build_app() -> ConnectorApp:
    public_host = urlparse(settings.mcp_public_base_url).netloc
    return ConnectorApp(mcp, client.token_is_valid, settings.mcp_rate_limit_per_minute, public_host)
