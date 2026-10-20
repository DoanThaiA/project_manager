async def test_login_failed_is_logged(client, login):
    resp = await client.post("/auth/login", data={"username": "admin", "password": "sai-mat-khau"})
    assert resp.status_code == 401

    logs = await client.get("/activity-logs", params={"action": "login_failed"}, headers=await login("admin"))
    assert logs.status_code == 200
    assert logs.json()["total"] >= 1


async def test_me_returns_system_permissions(client, login):
    resp = await client.get("/auth/me", headers=await login("po.an"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "po.an"
    assert [r["code"] for r in body["roles"]] == ["PROJECT_MANAGER"]
    assert "project.create" in body["permissions"]
    assert "user.create" not in body["permissions"]


async def test_requires_token(client):
    assert (await client.get("/auth/me")).status_code == 401


async def test_admin_creates_and_locks_user(client, login):
    admin = await login("admin")
    resp = await client.post(
        "/users",
        json={
            "username": "dev.moi",
            "email": "moi@example.com",
            "password": "Demo@123",
            "full_name": "Dev Mới",
            "role_ids": [3],
        },
        headers=admin,
    )
    assert resp.status_code == 201, resp.text
    user = resp.json()
    assert [r["code"] for r in user["roles"]] == ["STAFF"]

    dup = await client.post(
        "/users",
        json={"username": "dev.moi", "email": "x@example.com", "password": "Demo@123", "full_name": "x"},
        headers=admin,
    )
    assert dup.status_code == 409

    assert (await client.post(f"/users/{user['id']}/lock", headers=admin)).json()["status"] == "locked"
    resp = await client.post("/auth/login", data={"username": "dev.moi", "password": "Demo@123"})
    assert resp.status_code == 403


async def test_staff_cannot_create_user(client, login):
    resp = await client.post(
        "/users",
        json={"username": "hack", "email": "h@example.com", "password": "Demo@123", "full_name": "x"},
        headers=await login("dev.cuong"),
    )
    assert resp.status_code == 403


async def test_project_role_cannot_be_assigned_as_system_role(client, login):
    users = (await client.get("/users", params={"q": "qa.dung"}, headers=await login("admin"))).json()
    developer_role = next(
        r["id"] for r in (await client.get("/roles", headers=await login("admin"))).json() if r["code"] == "DEVELOPER"
    )
    resp = await client.put(
        f"/users/{users['items'][0]['id']}/roles", json={"role_ids": [developer_role]}, headers=await login("admin")
    )
    assert resp.status_code == 422
