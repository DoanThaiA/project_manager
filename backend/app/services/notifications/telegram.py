"""Gọi Telegram Bot API (https://core.telegram.org/bots/api)."""

from typing import Any

import httpx

from app.core.config import settings


class TelegramError(Exception):
    def __init__(self, status: int, description: str, parameters: dict | None = None):
        super().__init__(f"Telegram {status}: {description}")
        self.status = status
        self.description = description
        params = parameters or {}
        self.retry_after: int | None = params.get("retry_after")
        self.migrate_to_chat_id: int | None = params.get("migrate_to_chat_id")

    @property
    def chat_unreachable(self) -> bool:
        """Bot bị chặn / bị đuổi khỏi group / chat không còn: ngừng gửi tới chat này."""
        return self.status == 403 or (self.status == 400 and "chat not found" in self.description.lower())


def is_configured() -> bool:
    return bool(settings.telegram_bot_token)


async def call(method: str, http_timeout: float = 15, **params: Any) -> Any:
    url = f"{settings.telegram_api_url}/bot{settings.telegram_bot_token}/{method}"
    async with httpx.AsyncClient(timeout=http_timeout) as client:
        resp = await client.post(url, json={k: v for k, v in params.items() if v is not None})
    try:
        body = resp.json()
    except ValueError:
        raise TelegramError(resp.status_code, resp.text[:200]) from None
    if not body.get("ok"):
        raise TelegramError(
            body.get("error_code", resp.status_code), body.get("description", ""), body.get("parameters")
        )
    return body["result"]


async def send_message(chat_id: int, html: str) -> None:
    await call("sendMessage", chat_id=chat_id, text=html, parse_mode="HTML", link_preview_options={"is_disabled": True})


async def get_updates(offset: int | None, timeout: int = 30) -> list[dict]:
    return await call(
        "getUpdates",
        http_timeout=timeout + 10,
        # Long polling: Telegram giữ kết nối tới khi có tin hoặc hết `timeout` giây
        offset=offset,
        timeout=timeout,
        allowed_updates=["message", "my_chat_member"],
    )


_username: str | None = None


async def bot_username() -> str:
    """Username của bot (để tạo link t.me/...), lấy qua getMe một lần."""
    global _username
    if _username is None:
        _username = (await call("getMe"))["username"]
    return _username
