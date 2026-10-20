import pytest


async def test_create_admin_can_login(client):
    from app.cli import create_admin

    user = await create_admin("boss", "boss@example.com", "Sếp Tổng", "MatKhau@123")
    assert user.is_system_admin

    resp = await client.post("/auth/login", data={"username": "boss", "password": "MatKhau@123"})
    assert resp.status_code == 200
    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {resp.json()['access_token']}"})
    assert [r["code"] for r in me.json()["roles"]] == ["SYSTEM_ADMIN"]

    with pytest.raises(ValueError, match="đã tồn tại"):
        await create_admin("boss", "khac@example.com", "x", "MatKhau@123")
    with pytest.raises(ValueError, match="tối thiểu"):
        await create_admin("boss2", "boss2@example.com", "x", "ngan")
