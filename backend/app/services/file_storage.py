"""Lưu file đính kèm (tài liệu, PDF, Excel, zip...) trên MinIO (S3). Ảnh vẫn ở Cloudflare Images (storage.py).

attachments.storage = 'minio', storage_key là object key trong bucket. Trình duyệt tải file thẳng từ MinIO
qua URL ký sẵn (presigned) hết hạn sau file_url_expire_seconds, luôn kèm Content-Disposition: attachment.
"""

from datetime import timedelta
from functools import cache
from typing import BinaryIO
from urllib.parse import quote

from fastapi import HTTPException, status
from minio import Minio
from minio.error import MinioException
from starlette.concurrency import run_in_threadpool

from app.core.config import settings


def is_configured() -> bool:
    return all((settings.minio_endpoint, settings.minio_access_key, settings.minio_secret_key, settings.minio_bucket))


@cache
def _client(endpoint: str) -> Minio:
    return Minio(
        endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
        region=settings.minio_region,
    )


def _api() -> Minio:
    if not is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chưa cấu hình lưu trữ file (MinIO: MINIO_ENDPOINT, MINIO_ACCESS_KEY, ...)",
        )
    return _client(settings.minio_endpoint)


async def upload(key: str, data: BinaryIO, size: int, content_type: str) -> None:
    client = _api()
    try:
        await run_in_threadpool(client.put_object, settings.minio_bucket, key, data, size, content_type=content_type)
    except MinioException as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"MinIO lỗi: {exc}") from exc


async def delete(key: str) -> None:
    client = _api()
    await run_in_threadpool(client.remove_object, settings.minio_bucket, key)  # không có object cũng không lỗi


def download_url(key: str, file_name: str) -> str:
    """URL tải file ký sẵn; ký offline (đã đặt region) nên không gọi tới MinIO."""
    if not is_configured():
        return ""
    client = _client(settings.minio_public_endpoint or settings.minio_endpoint)
    ascii_name = file_name.encode("ascii", "ignore").decode().replace('"', "").strip() or "file"
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(file_name)}"
    return client.presigned_get_object(
        settings.minio_bucket,
        key,
        expires=timedelta(seconds=settings.file_url_expire_seconds),
        response_headers={"response-content-disposition": disposition},
    )
