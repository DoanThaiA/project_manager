"""Lưu ảnh trên Cloudflare Images (https://developers.cloudflare.com/images/)."""

import hashlib
import hmac
import json
import time

import httpx
from fastapi import HTTPException, status

from app.core.config import settings

_API = "https://api.cloudflare.com/client/v4/accounts/{account}/images/v1"
_DELIVERY = "https://imagedelivery.net"


def is_configured() -> bool:
    return all((settings.cf_account_id, settings.cf_images_token, settings.cf_images_account_hash))


def _api_url(image_id: str = "") -> str:
    if not is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chưa cấu hình lưu trữ ảnh (Cloudflare Images: CF_ACCOUNT_ID, CF_IMAGES_TOKEN, ...)",
        )
    base = _API.format(account=settings.cf_account_id)
    return f"{base}/{image_id}" if image_id else base


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.cf_images_token}"}


def _check(resp: httpx.Response) -> dict:
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if resp.is_error or not body.get("success"):
        errors = "; ".join(e.get("message", "") for e in body.get("errors", [])) or resp.text[:200]
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Cloudflare Images lỗi: {errors}")
    return body


async def upload_image(data: bytes, file_name: str, content_type: str, metadata: dict) -> str:
    """Tải ảnh lên, trả về image id do Cloudflare sinh (lưu vào attachments.storage_key)."""
    form = {"metadata": json.dumps(metadata)}
    if settings.cf_images_signing_key:
        form["requireSignedURLs"] = "true"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            _api_url(), headers=_headers(), data=form, files={"file": (file_name, data, content_type)}
        )
    return _check(resp)["result"]["id"]


async def delete_image(image_id: str) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.delete(_api_url(image_id), headers=_headers())
    if resp.status_code != 404:  # đã bị xoá trên Cloudflare thì coi như xong
        _check(resp)


def image_url(image_id: str) -> str:
    """URL hiển thị ảnh; ảnh riêng tư thì ký HMAC-SHA256 kèm hạn dùng."""
    path = f"/{settings.cf_images_account_hash}/{image_id}/{settings.cf_images_variant}"
    if not settings.cf_images_signing_key:
        return f"{_DELIVERY}{path}"
    expires = int(time.time()) + settings.cf_images_url_expire_seconds
    to_sign = f"{path}?exp={expires}"
    sig = hmac.new(settings.cf_images_signing_key.encode(), to_sign.encode(), hashlib.sha256).hexdigest()
    return f"{_DELIVERY}{to_sign}&sig={sig}"
