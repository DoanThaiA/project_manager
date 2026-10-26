from urllib.parse import parse_qs, unquote, urlsplit

import pytest

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.7\n" + b"x" * 100


@pytest.fixture
def fake_minio(monkeypatch):
    """Thay MinIO bằng dict trong bộ nhớ."""
    from app.services import file_storage

    objects: dict[str, tuple[bytes, str]] = {}

    async def upload(key, data, size, content_type):
        content = data.read()
        assert len(content) == size
        objects[key] = (content, content_type)

    async def delete(key):
        objects.pop(key, None)

    monkeypatch.setattr(file_storage, "upload", upload)
    monkeypatch.setattr(file_storage, "delete", delete)
    monkeypatch.setattr(file_storage, "download_url", lambda key, name: f"https://minio.test/bucket/{key}")
    return objects


async def test_work_item_files(client, login, project_id, fake_minio):
    dev = await login("dev.cuong")
    url = f"/projects/{project_id}/work-items/1/files"

    up = await client.post(url, files={"file": ("Đặc tả v2.pdf", PDF, "application/pdf")}, headers=dev)
    assert up.status_code == 201, up.text
    f = up.json()
    assert f["file_name"] == "Đặc tả v2.pdf" and f["mime_type"] == "application/pdf" and f["size_bytes"] == len(PDF)
    assert f["category"] is None
    [(key, (content, mime))] = fake_minio.items()
    assert key.startswith(f"projects/{project_id}/work_item/1/") and key.endswith(".pdf")
    assert content == PDF and mime == "application/pdf"
    assert f["url"] == f"https://minio.test/bucket/{key}"

    listed = (await client.get(url, headers=dev)).json()
    assert [a["id"] for a in listed] == [f["id"]]

    # File không lẫn vào danh sách ảnh, và không xoá được qua endpoint ảnh
    images = (await client.get(f"/projects/{project_id}/work-items/1/attachments", headers=dev)).json()
    assert f["id"] not in [a["id"] for a in images]
    resp = await client.delete(f"/projects/{project_id}/work-items/1/attachments/{f['id']}", headers=dev)
    assert resp.status_code == 404

    # Sai công việc -> 404
    assert (await client.delete(f"/projects/{project_id}/work-items/2/files/{f['id']}", headers=dev)).status_code == 404

    assert (await client.delete(f"{url}/{f['id']}", headers=dev)).status_code == 204
    assert (await client.get(url, headers=dev)).json() == []
    assert fake_minio == {}


async def test_image_cannot_be_deleted_as_file(client, login, project_id, fake_minio, monkeypatch):
    from app.services import storage

    async def upload_image(data, file_name, content_type, metadata):
        return "img-x"

    monkeypatch.setattr(storage, "upload_image", upload_image)
    dev = await login("dev.cuong")
    img = await client.post(
        f"/projects/{project_id}/work-items/2/attachments",
        files={"file": ("loi.png", PNG, "image/png")},
        data={"category": "bug"},
        headers=dev,
    )
    assert img.status_code == 201
    assert (await client.get(f"/projects/{project_id}/work-items/2/files", headers=dev)).json() == []
    resp = await client.delete(f"/projects/{project_id}/work-items/2/files/{img.json()['id']}", headers=dev)
    assert resp.status_code == 404


async def test_requirement_files(client, login, project_id, fake_minio):
    po, customer = await login("po.an"), await login("kh.abc")
    url = f"/projects/{project_id}/requirements/1/files"

    up = await client.post(url, files={"file": ("bao-gia.xlsx", b"PK\x03\x04data", "")}, headers=po)
    assert up.status_code == 201, up.text
    # Không có Content-Type -> đoán theo đuôi file
    assert up.json()["mime_type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    listed = await client.get(url, headers=customer)
    assert listed.status_code == 200 and [a["file_name"] for a in listed.json()] == ["bao-gia.xlsx"]

    resp = await client.post(url, files={"file": ("x.txt", b"x", "text/plain")}, headers=customer)
    assert resp.status_code == 403


async def test_upload_limits(client, login, project_id, fake_minio, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "file_max_mb", 1)
    dev = await login("dev.cuong")
    url = f"/projects/{project_id}/work-items/1/files"
    big = await client.post(url, files={"file": ("big.zip", b"0" * (1024 * 1024 + 1), "application/zip")}, headers=dev)
    assert big.status_code == 413
    empty = await client.post(url, files={"file": ("empty.txt", b"", "text/plain")}, headers=dev)
    assert empty.status_code == 422
    missing = await client.post(
        f"/projects/{project_id}/work-items/999999/files", files={"file": ("a.txt", b"a")}, headers=dev
    )
    assert missing.status_code == 404
    assert fake_minio == {}


def test_download_url_is_presigned_attachment(monkeypatch):
    from app.core.config import settings
    from app.services import file_storage

    for name, value in {
        "minio_endpoint": "minio:9000",
        "minio_public_endpoint": "files.example.com",
        "minio_secure": True,
        "minio_access_key": "key",
        "minio_secret_key": "secret",
        "minio_bucket": "pm-files",
    }.items():
        monkeypatch.setattr(settings, name, value)
    file_storage._client.cache_clear()

    url = urlsplit(file_storage.download_url("projects/1/work_item/1/abc.pdf", "Đặc tả.pdf"))
    assert (url.scheme, url.netloc, url.path) == (
        "https",
        "files.example.com",
        "/pm-files/projects/1/work_item/1/abc.pdf",
    )
    qs = parse_qs(url.query)
    assert "X-Amz-Signature" in qs
    disposition = unquote(qs["response-content-disposition"][0])
    assert disposition.startswith('attachment; filename="c t.pdf"') and "Đặc tả.pdf" in unquote(disposition)
    file_storage._client.cache_clear()
