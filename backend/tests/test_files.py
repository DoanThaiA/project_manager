from urllib.parse import parse_qs, unquote, urlsplit

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.7\n" + b"x" * 100


async def test_work_item_files(client, login, project_id, fake_r2):
    dev = await login("dev.cuong")
    url = f"/projects/{project_id}/work-items/1/files"

    up = await client.post(url, files={"file": ("Đặc tả v2.pdf", PDF, "application/pdf")}, headers=dev)
    assert up.status_code == 201, up.text
    f = up.json()
    assert f["file_name"] == "Đặc tả v2.pdf" and f["mime_type"] == "application/pdf" and f["size_bytes"] == len(PDF)
    assert f["category"] is None
    [(key, (content, mime))] = fake_r2.items()
    assert key.startswith(f"projects/{project_id}/work-items/1/") and key.endswith(".pdf")
    assert content == PDF and mime == "application/pdf"
    assert f["url"] == f"https://r2.test/bucket/{key}"

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
    assert fake_r2 == {}


async def test_image_cannot_be_deleted_as_file(client, login, project_id, fake_r2, monkeypatch):
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


async def test_requirement_files(client, login, project_id, fake_r2):
    po, customer = await login("po.an"), await login("kh.abc")
    url = f"/projects/{project_id}/requirements/1/files"

    up = await client.post(url, files={"file": ("bao-gia.xlsx", b"PK\x03\x04data", "")}, headers=po)
    assert up.status_code == 201, up.text
    # Không có Content-Type -> đoán theo đuôi file
    assert up.json()["mime_type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    assert next(k for k in fake_r2 if k.endswith(".xlsx")).startswith(f"projects/{project_id}/requirements/1/")

    listed = await client.get(url, headers=customer)
    assert listed.status_code == 200 and [a["file_name"] for a in listed.json()] == ["bao-gia.xlsx"]

    resp = await client.post(url, files={"file": ("x.txt", b"x", "text/plain")}, headers=customer)
    assert resp.status_code == 403


async def test_upload_limits(client, login, project_id, fake_r2, monkeypatch):
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
    assert fake_r2 == {}


def test_download_url_is_presigned_attachment(monkeypatch):
    from app.core.config import settings
    from app.services import file_storage

    for name, value in {
        "r2_account_id": "acc123",
        "r2_access_key_id": "key",
        "r2_secret_access_key": "secret",
        "r2_bucket": "pm-files",
    }.items():
        monkeypatch.setattr(settings, name, value)
    file_storage._client.cache_clear()

    url = urlsplit(file_storage.download_url("projects/1/work_item/1/abc.pdf", "Đặc tả.pdf"))
    assert (url.scheme, url.netloc, url.path) == (
        "https",
        "acc123.r2.cloudflarestorage.com",
        "/pm-files/projects/1/work_item/1/abc.pdf",
    )
    qs = parse_qs(url.query)
    assert "X-Amz-Signature" in qs and "/auto/s3/" in qs["X-Amz-Credential"][0]
    disposition = unquote(qs["response-content-disposition"][0])
    assert disposition.startswith('attachment; filename="c t.pdf"') and "Đặc tả.pdf" in unquote(disposition)
    file_storage._client.cache_clear()


async def test_inline_files(client, login, project_id, fake_r2, monkeypatch):
    from app.api.v1.endpoints import attachments

    # URL ảnh Cloudflare không cần trong test này
    monkeypatch.setattr(attachments.storage, "image_url", lambda image_id: f"https://img.test/{image_id}")
    dev = await login("dev.cuong")
    name = "0123456789abcdef/Biên bản họp.docx"

    up = await client.post(
        f"/projects/{project_id}/inline-files",
        files={"file": ("x.docx", b"PK\x03\x04docx", "")},
        data={"name": name, "folder": "work-logs"},
        headers=dev,
    )
    assert up.status_code == 201, up.text
    assert up.json()["file_name"] == name and up.json()["entity_id"] == project_id
    [key] = fake_r2
    assert key.startswith(f"projects/{project_id}/text/work-logs/") and key.endswith(".docx")

    # Tra theo tên qua endpoint dùng chung với ảnh dán trong văn bản
    resolved = await client.get(f"/projects/{project_id}/inline-images", params={"names": [name]}, headers=dev)
    assert [(a["file_name"], a["url"]) for a in resolved.json()] == [(name, f"https://r2.test/bucket/{key}")]

    for bad in ("Biên bản.docx", "0123456789abcdef/a]b.docx", "0123456789abcdef/../x", "XYZ/abc.pdf"):
        resp = await client.post(
            f"/projects/{project_id}/inline-files", files={"file": ("x", b"x")}, data={"name": bad}, headers=dev
        )
        assert resp.status_code == 422, bad
    resp = await client.post(
        f"/projects/{project_id}/inline-files",
        files={"file": ("x.pdf", b"x")},
        data={"name": "0123456789abcdef/x.pdf", "folder": "../../etc"},
        headers=dev,
    )
    assert resp.status_code == 422
    assert len(fake_r2) == 1

    # Không gửi folder -> nhóm "other"
    other = await client.post(
        f"/projects/{project_id}/inline-files",
        files={"file": ("y.pdf", b"y")},
        data={"name": "fedcba9876543210/y.pdf"},
        headers=dev,
    )
    assert other.status_code == 201
    assert any(k.startswith(f"projects/{project_id}/text/other/") for k in fake_r2)
