import hashlib
import hmac
from urllib.parse import parse_qs, urlsplit

import pytest

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def fake_images(monkeypatch):
    """Thay Cloudflare Images bằng dict trong bộ nhớ."""
    from app.services import storage

    images: dict[str, bytes] = {}

    async def upload_image(data, file_name, content_type, metadata):
        image_id = f"img-{len(images) + 1}-{metadata['work_item_id']}"
        images[image_id] = data
        return image_id

    async def delete_image(image_id):
        images.pop(image_id, None)

    monkeypatch.setattr(storage, "upload_image", upload_image)
    monkeypatch.setattr(storage, "delete_image", delete_image)
    monkeypatch.setattr(storage, "image_url", lambda image_id: f"https://imagedelivery.net/hash/{image_id}/public")
    return images


async def test_upload_list_delete_images(client, login, project_id, fake_images):
    dev = await login("dev.cuong")
    url = f"/projects/{project_id}/work-items/1/attachments"

    bug = await client.post(url, files={"file": ("loi.png", PNG, "image/png")}, data={"category": "bug"}, headers=dev)
    assert bug.status_code == 201, bug.text
    bug = bug.json()
    assert bug["category"] == "bug" and bug["mime_type"] == "image/png" and bug["size_bytes"] == len(PNG)
    assert bug["url"] == "https://imagedelivery.net/hash/img-1-1/public"
    assert len(fake_images) == 1

    result = await client.post(
        url, files={"file": ("ok.png", PNG, "image/png")}, data={"category": "result"}, headers=dev
    )
    assert result.status_code == 201

    listed = (await client.get(url, headers=dev)).json()
    assert [a["category"] for a in listed] == ["bug", "result"]

    assert (await client.delete(f"{url}/{bug['id']}", headers=dev)).status_code == 204
    assert [a["id"] for a in (await client.get(url, headers=dev)).json()] == [result.json()["id"]]
    assert len(fake_images) == 1


async def test_upload_rejects_non_image(client, login, project_id, fake_images):
    dev = await login("dev.cuong")
    url = f"/projects/{project_id}/work-items/2/attachments"
    resp = await client.post(
        url, files={"file": ("x.png", b"<svg onload=alert(1)>", "image/png")}, data={"category": "bug"}, headers=dev
    )
    assert resp.status_code == 422
    resp = await client.post(url, files={"file": ("x.png", PNG, "image/png")}, data={"category": "other"}, headers=dev)
    assert resp.status_code == 422
    assert fake_images == {}


def test_signed_image_url(monkeypatch):
    from app.core.config import settings
    from app.services import storage

    monkeypatch.setattr(settings, "cf_images_account_hash", "hash")
    monkeypatch.setattr(settings, "cf_images_signing_key", "secret")
    url = urlsplit(storage.image_url("abc"))
    assert url.path == "/hash/abc/public"
    qs = parse_qs(url.query)
    expected = hmac.new(b"secret", f"/hash/abc/public?exp={qs['exp'][0]}".encode(), hashlib.sha256).hexdigest()
    assert qs["sig"] == [expected]

    monkeypatch.setattr(settings, "cf_images_signing_key", "")
    assert storage.image_url("abc") == "https://imagedelivery.net/hash/abc/public"
