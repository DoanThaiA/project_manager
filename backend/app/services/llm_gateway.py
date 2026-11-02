"""AI Gateway tối giản (docs/LLM_GATEWAY.md): mã hoá key nhà cung cấp, key dự án, đọc usage, tính chi phí.

Gateway chuyển tiếp NGUYÊN định dạng của từng nhà cung cấp (không chuyển đổi), nên Anthropic SDK / OpenAI SDK dùng
được trực tiếp, chỉ đổi base_url + api_key. Nhà cung cấp cấu hình động (bảng llm_providers); cách gửi key + đường dẫn
được phép đi theo định dạng API: 'anthropic' hoặc 'openai' (Grok, DeepSeek, OpenRouter, Ollama... đều tương thích
OpenAI). Usage đọc từ phản hồi (JSON hoặc SSE) để tính chi phí.
"""

import json
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.security import hash_api_token

CLIENT_KEY_PREFIX = "pm_llm_"

API_FORMATS = ("openai", "anthropic")

# Đường dẫn (sau /v1/) được phép chuyển tiếp theo định dạng API; True = request tính tiền (cần model + ghi usage)
FORMAT_PATHS: dict[str, dict[str, bool]] = {
    "anthropic": {"messages": True, "messages/count_tokens": False},
    "openai": {"chat/completions": True, "responses": True, "embeddings": True, "completions": True},
}


def upstream_url(base_url: str, path: str) -> str:
    """base_url gồm phần phiên bản (vd https://api.x.ai/v1) + đường dẫn (chat/completions)."""
    return f"{base_url.rstrip('/')}/{path}"


# ---------------------------------------------------------------- Mã hoá key nhà cung cấp


class GatewayDisabled(Exception):
    """Chưa đặt LLM_ENCRYPTION_KEY."""


def _fernet() -> Fernet:
    if not settings.llm_encryption_key:
        raise GatewayDisabled("Chưa cấu hình LLM_ENCRYPTION_KEY (docs/LLM_GATEWAY.md)")
    return Fernet(settings.llm_encryption_key.encode())


def encrypt_key(raw: str) -> str:
    return _fernet().encrypt(raw.encode()).decode()


def decrypt_key(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:  # đổi LLM_ENCRYPTION_KEY sau khi đã lưu key
        raise GatewayDisabled("Không giải mã được key: LLM_ENCRYPTION_KEY đã bị đổi?") from exc


def key_hint(raw: str) -> str:
    return "••••" + raw[-4:]


def upstream_headers(api_format: str, raw_key: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Header xác thực theo định dạng API + header bổ sung của nhà cung cấp (không ghi đè được header xác thực)."""
    auth = {"x-api-key": raw_key} if api_format == "anthropic" else {"authorization": f"Bearer {raw_key}"}
    return {**{k.lower(): str(v) for k, v in (extra or {}).items()}, **auth}


# ---------------------------------------------------------------- Key dự án


def new_client_key() -> str:
    return CLIENT_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_client_key(key: str) -> str:
    return hash_api_token(key)


def client_key_from_headers(headers: httpx.Headers | Any) -> str | None:
    """Anthropic SDK gửi x-api-key, OpenAI SDK gửi Authorization: Bearer."""
    if key := headers.get("x-api-key"):
        return key.strip()
    auth = headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


class RateLimiter:
    """Giới hạn request / phút theo key dự án, trong bộ nhớ (một process API)."""

    def __init__(self) -> None:
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    def allow(self, key_id: int, limit: int, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        hits = self._hits[key_id]
        while hits and now - hits[0] >= 60:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True


rate_limiter = RateLimiter()


# ---------------------------------------------------------------- Usage + chi phí


@dataclass
class Usage:
    input_tokens: int = 0  # không tính phần đọc cache
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def merge(self, other: "Usage") -> None:
        """Gộp usage từ nhiều sự kiện stream: lấy giá trị lớn nhất (các số đều là luỹ kế)."""
        self.input_tokens = max(self.input_tokens, other.input_tokens)
        self.output_tokens = max(self.output_tokens, other.output_tokens)
        self.cache_read_tokens = max(self.cache_read_tokens, other.cache_read_tokens)
        self.cache_write_tokens = max(self.cache_write_tokens, other.cache_write_tokens)


def _int(value: Any) -> int:
    return value if isinstance(value, int) else 0


def _normalize(usage: dict[str, Any]) -> Usage:
    """Usage của Anthropic (input_tokens không gồm cache) hoặc OpenAI (prompt_tokens / input_tokens gồm cache)."""
    if "cache_read_input_tokens" in usage or "cache_creation_input_tokens" in usage:  # Anthropic
        return Usage(
            input_tokens=_int(usage.get("input_tokens")),
            output_tokens=_int(usage.get("output_tokens")),
            cache_read_tokens=_int(usage.get("cache_read_input_tokens")),
            cache_write_tokens=_int(usage.get("cache_creation_input_tokens")),
        )
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    cached = _int(details.get("cached_tokens")) if isinstance(details, dict) else 0
    total_in = _int(usage.get("prompt_tokens", usage.get("input_tokens")))
    return Usage(
        input_tokens=max(total_in - cached, 0),
        output_tokens=_int(usage.get("completion_tokens", usage.get("output_tokens"))),
        cache_read_tokens=cached,
    )


def usage_from_event(obj: Any) -> Usage | None:
    """Usage trong một JSON phản hồi hoặc một sự kiện SSE (Anthropic message_start / message_delta,
    OpenAI chunk cuối có usage, Responses API response.completed)."""
    if not isinstance(obj, dict):
        return None
    kind = obj.get("type")
    if kind == "message_start":
        usage = (obj.get("message") or {}).get("usage")
    elif kind in ("response.completed", "response.incomplete", "response.failed"):
        usage = (obj.get("response") or {}).get("usage")
    else:
        usage = obj.get("usage")
    return _normalize(usage) if isinstance(usage, dict) else None


class SseUsageReader:
    """Đọc usage từ luồng SSE theo từng chunk byte (chunk có thể cắt ngang dòng)."""

    def __init__(self) -> None:
        self.usage = Usage()
        self.found = False
        self._buffer = b""

    def feed(self, chunk: bytes) -> None:
        self._buffer += chunk
        *lines, self._buffer = self._buffer.split(b"\n")
        for line in lines:
            self._line(line)

    def close(self) -> None:
        if self._buffer:
            self._line(self._buffer)
            self._buffer = b""

    def _line(self, line: bytes) -> None:
        line = line.strip()
        if not line.startswith(b"data:"):
            return
        data = line[5:].strip()
        if not data or data == b"[DONE]":
            return
        try:
            usage = usage_from_event(json.loads(data))
        except ValueError:
            return
        if usage:
            self.usage.merge(usage)
            self.found = True


def cost_usd(usage: Usage, prices: Any) -> Decimal:
    """prices: LlmModel (giá USD / 1 triệu token). Giá cache bỏ trống thì tính như giá input."""
    if prices is None:
        return Decimal(0)
    cache_read = prices.cache_read_price if prices.cache_read_price is not None else prices.input_price
    cache_write = prices.cache_write_price if prices.cache_write_price is not None else prices.input_price
    total = (
        usage.input_tokens * prices.input_price
        + usage.output_tokens * prices.output_price
        + usage.cache_read_tokens * cache_read
        + usage.cache_write_tokens * cache_write
    )
    return (Decimal(total) / Decimal(1_000_000)).quantize(Decimal("0.000001"))


# ---------------------------------------------------------------- HTTP tới nhà cung cấp

# Test thay bằng httpx.MockTransport
upstream_transport: httpx.AsyncBaseTransport | None = None
_client: httpx.AsyncClient | None = None


def upstream_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            transport=upstream_transport,
            timeout=httpx.Timeout(settings.llm_upstream_timeout_seconds, connect=10),
        )
    return _client


async def close_upstream_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
