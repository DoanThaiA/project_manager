"""Lưu file đính kèm (tài liệu, PDF, Excel, zip...) trên Cloudflare R2. Ảnh vẫn ở Cloudflare Images (storage.py).

attachments.storage = 'r2', storage_key là object key trong bucket. R2 tương thích S3 nên dùng client S3 của
thư viện `minio`. Trình duyệt tải file thẳng từ R2 qua URL ký sẵn (presigned) hết hạn sau
file_url_expire_seconds, luôn kèm Content-Disposition: attachment.
"""

import mimetypes
from datetime import timedelta
from functools import cache
from typing import BinaryIO
from urllib.parse import quote

from fastapi import HTTPException, status
from minio import Minio
from minio.error import MinioException
from starlette.concurrency import run_in_threadpool

from app.core.config import settings

STORAGE = "r2"


def is_configured() -> bool:
    return all((settings.r2_account_id, settings.r2_access_key_id, settings.r2_secret_access_key, settings.r2_bucket))


@cache
def _client(endpoint: str) -> Minio:
    # region "auto": R2 không có region; đặt sẵn để ký URL không phải hỏi server
    return Minio(
        endpoint,
        access_key=settings.r2_access_key_id,
        secret_key=settings.r2_secret_access_key,
        secure=True,
        region="auto",
    )


def _r2() -> Minio:
    if not is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chưa cấu hình lưu trữ file (Cloudflare R2: R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, ...)",
        )
    return _client(settings.r2_endpoint or f"{settings.r2_account_id}.r2.cloudflarestorage.com")


async def upload(key: str, data: BinaryIO, size: int, content_type: str) -> None:
    client = _r2()
    try:
        await run_in_threadpool(client.put_object, settings.r2_bucket, key, data, size, content_type=content_type)
    except MinioException as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Cloudflare R2 lỗi: {exc}") from exc


async def delete(key: str) -> None:
    client = _r2()
    await run_in_threadpool(client.remove_object, settings.r2_bucket, key)  # không có object cũng không lỗi


def _disposition(kind: str, file_name: str) -> str:
    ascii_name = file_name.encode("ascii", "ignore").decode().replace('"', "").strip() or "file"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(file_name)}"


def _presign(key: str, response_headers: dict[str, str]) -> str:
    """URL ký sẵn; ký offline nên không gọi tới R2."""
    if not is_configured():
        return ""
    return _r2().presigned_get_object(
        settings.r2_bucket,
        key,
        expires=timedelta(seconds=settings.file_url_expire_seconds),
        response_headers=response_headers,
    )


def download_url(key: str, file_name: str) -> str:
    """URL tải file về máy (Content-Disposition: attachment)."""
    return _presign(key, {"response-content-disposition": _disposition("attachment", file_name)})


# Hiện dạng văn bản thuần. HTML / SVG / XML cũng chỉ hiện mã nguồn: không bao giờ để trình duyệt chạy script trong file
_TEXT_EXT = {
    "txt", "log", "md", "csv", "tsv", "json", "xml", "yaml", "yml", "ini", "conf", "env", "sql",
    "html", "htm", "svg", "css", "js", "ts", "tsx", "jsx", "py", "java", "cs", "php", "go", "rb", "sh", "bat",
}  # fmt: skip
_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "avif"}
_VIDEO_EXT = {"mp4", "webm", "mov", "m4v", "ogv"}
_AUDIO_EXT = {"mp3", "wav", "ogg", "m4a", "aac", "flac"}
_OFFICE_EXT = {"doc", "docx", "xls", "xlsx", "ppt", "pptx"}


def preview_kind(file_name: str) -> str | None:
    """Kiểu xem trực tiếp theo đuôi file (không tin mime do trình duyệt gửi lên); None = chỉ tải về."""
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    if ext == "pdf":
        return "pdf"
    if ext in _IMAGE_EXT:
        return "image"
    if ext in _VIDEO_EXT:
        return "video"
    if ext in _AUDIO_EXT:
        return "audio"
    if ext in _TEXT_EXT:
        return "text"
    if ext in _OFFICE_EXT and settings.file_office_preview:
        return "office"
    return None


def preview_url(key: str, file_name: str, kind: str) -> str:
    """URL xem trực tiếp (Content-Disposition: inline). Content-Type suy từ đuôi file, không dùng mime lúc tải lên
    (người tải lên tự đặt được) — để một file .png không thể được trình duyệt hiển thị như HTML."""
    if kind == "text":
        content_type = "text/plain; charset=utf-8"
    else:
        content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    return _presign(
        key,
        {
            "response-content-disposition": _disposition("inline", file_name),
            "response-content-type": content_type,
        },
    )
