import pytest

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

CARD = """CÔNG TY CỔ PHẦN PHẦN MỀM XYZ
TRẦN THỊ BÍCH NGỌC
Trưởng phòng Kinh doanh
Tầng 5, 123 Nguyễn Huệ, Quận 1, TP.HCM
T: (028) 3823 4567 - M: +84 903 123 456
Fax: 028 3823 4568
E: Ngoc.Tran@xyz.com.vn"""

COMPANY = """CÔNG TY TNHH THƯƠNG MẠI AN PHÁT
MST: 0312 345 678
Địa chỉ: 45 Lê Lợi, P. Bến Nghé, Q.1, TP.HCM
Hotline: 1900 1234
Email: info@anphat.vn
www.anphat.vn"""


@pytest.fixture
async def customer_id(client, login) -> int:
    resp = await client.get("/customers", params={"q": "KH001"}, headers=await login("admin"))
    return resp.json()["items"][0]["id"]


@pytest.fixture
def fake_ocr(monkeypatch):
    from app.services import ocr

    calls: list[tuple[str, str]] = []

    async def read_text(data, file_name, content_type):
        calls.append((file_name, content_type))
        return COMPANY if data.startswith(PNG) else CARD

    monkeypatch.setattr(ocr, "read_text", read_text)
    return calls


def test_parse_card():
    from app.services.ocr import parse_card

    assert parse_card(CARD) == {
        "full_name": "Trần Thị Bích Ngọc",
        "position": "Trưởng phòng Kinh doanh",
        "email": "ngoc.tran@xyz.com.vn",
        "phone": "+84 903 123 456",  # ưu tiên số di động, bỏ qua fax
        "company": "CÔNG TY CỔ PHẦN PHẦN MỀM XYZ",
    }
    assert parse_card("ABC Group\nJohn Smith\nSales Director\nMobile: 0987.654.321\nwww.abc.com") == {
        "full_name": "John Smith",
        "position": "Sales Director",
        "email": None,
        "phone": "0987.654.321",
        "company": "ABC Group",
    }
    assert parse_card("") == dict.fromkeys(("full_name", "position", "email", "phone", "company"))


def test_parse_company():
    from app.services.ocr import parse_company

    assert parse_company(COMPANY) == {
        "name": "CÔNG TY TNHH THƯƠNG MẠI AN PHÁT",
        "tax_code": "0312345678",  # không nhầm sang số điện thoại
        "email": "info@anphat.vn",
        "phone": "1900 1234",
        "address": "45 Lê Lợi, P. Bến Nghé, Q.1, TP.HCM",
        "website": "www.anphat.vn",
    }
    # Danh thiếp cá nhân: lấy số bàn công ty, địa chỉ không nhãn
    assert parse_company(CARD) == {
        "name": "CÔNG TY CỔ PHẦN PHẦN MỀM XYZ",
        "tax_code": None,
        "email": "ngoc.tran@xyz.com.vn",
        "phone": "(028) 3823 4567",
        "address": "Tầng 5, 123 Nguyễn Huệ, Quận 1, TP.HCM",
        "website": None,
    }


async def test_contact_crud(client, login, customer_id):
    po = await login("po.an")
    url = f"/customers/{customer_id}/contacts"

    created = await client.post(url, json={"full_name": "Nguyễn Văn A", "phone": "0912345678"}, headers=po)
    assert created.status_code == 201, created.text
    cid = created.json()["id"]

    updated = await client.patch(
        f"{url}/{cid}", json={"position": "Kế toán", "email": "a@abc.vn", "is_primary": True}, headers=po
    )
    assert updated.status_code == 200, updated.text
    assert updated.json() | {"id": 0} == {
        "id": 0,
        "customer_id": customer_id,
        "full_name": "Nguyễn Văn A",
        "position": "Kế toán",
        "email": "a@abc.vn",
        "phone": "0912345678",
        "is_primary": True,
    }
    listed = (await client.get(url, headers=po)).json()
    assert [c["id"] for c in listed if c["is_primary"]] == [cid]  # chỉ một đầu mối chính

    assert (await client.delete(f"{url}/{cid}", headers=po)).status_code == 204
    assert cid not in [c["id"] for c in (await client.get(url, headers=po)).json()]


async def test_ocr_card(client, login, customer_id, fake_ocr):
    url = f"/customers/{customer_id}/contacts/ocr"
    resp = await client.post(url, files={"file": ("card.jpg", JPEG, "image/jpeg")}, headers=await login("po.an"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["full_name"] == "Trần Thị Bích Ngọc" and body["phone"] == "+84 903 123 456"
    assert body["text"] == CARD
    assert fake_ocr == [("card.jpg", "image/jpeg")]


async def test_ocr_card_validation(client, login, customer_id, fake_ocr, monkeypatch):
    from app.core.config import settings

    url = f"/customers/{customer_id}/contacts/ocr"
    po = await login("po.an")
    bad = await client.post(url, files={"file": ("x.jpg", b"<svg/>", "image/jpeg")}, headers=po)
    assert bad.status_code == 422

    monkeypatch.setattr(settings, "ocr_max_kb", 1)
    big = await client.post(url, files={"file": ("big.jpg", JPEG + b"\x00" * 2048, "image/jpeg")}, headers=po)
    assert big.status_code == 413

    staff = await client.post(url, files={"file": ("card.jpg", JPEG, "image/jpeg")}, headers=await login("dev.cuong"))
    assert staff.status_code == 403
    assert fake_ocr == []


async def test_ocr_customer(client, login, fake_ocr):
    resp = await client.post(
        "/customers/ocr", files={"file": ("card.png", PNG, "image/png")}, headers=await login("po.an")
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "CÔNG TY TNHH THƯƠNG MẠI AN PHÁT" and body["tax_code"] == "0312345678"
    assert body["text"] == COMPANY

    staff = await client.post(
        "/customers/ocr", files={"file": ("card.png", PNG, "image/png")}, headers=await login("dev.cuong")
    )
    assert staff.status_code == 403
    assert fake_ocr == [("card.png", "image/png")]
