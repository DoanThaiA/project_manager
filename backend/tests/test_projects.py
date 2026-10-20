async def test_create_project_adds_po_as_member(client, login):
    headers = await login("po.an")
    resp = await client.post("/projects", json={"key": "CRM", "name": "Hệ thống CRM"}, headers=headers)
    assert resp.status_code == 201, resp.text
    project = resp.json()

    members = (await client.get(f"/projects/{project['id']}/members", headers=headers)).json()
    assert [(m["user"]["username"], [r["code"] for r in m["roles"]]) for m in members] == [("po.an", ["PRODUCT_OWNER"])]

    dup = await client.post("/projects", json={"key": "CRM", "name": "Trùng"}, headers=headers)
    assert dup.status_code == 409


async def test_non_member_cannot_access_project(client, login, project_id):
    # Tạo user không thuộc dự án ERP
    admin = await login("admin")
    await client.post(
        "/users",
        json={"username": "outsider", "email": "out@example.com", "password": "Demo@123", "full_name": "Người ngoài"},
        headers=admin,
    )
    headers = await login("outsider")
    assert (await client.get(f"/projects/{project_id}", headers=headers)).status_code == 403
    listed = (await client.get("/projects", headers=headers)).json()
    assert listed["total"] == 0


async def test_my_permissions_by_role(client, login, project_id):
    dev = (await client.get(f"/projects/{project_id}/my-permissions", headers=await login("dev.cuong"))).json()
    customer = (await client.get(f"/projects/{project_id}/my-permissions", headers=await login("kh.abc"))).json()
    assert "work_log.create" in dev and "requirement.approve" not in dev
    assert set(customer) == {"project.view", "requirement.view", "requirement.create", "requirement.comment"}


async def test_add_member_requires_project_role(client, login, project_id):
    headers = await login("sm.binh")
    roles = {r["code"]: r["id"] for r in (await client.get("/roles", headers=headers)).json()}
    users = (await client.get("/users", params={"q": "outsider"}, headers=headers)).json()["items"]

    bad = await client.post(
        f"/projects/{project_id}/members",
        json={"user_id": users[0]["id"], "role_ids": [roles["SYSTEM_ADMIN"]]},
        headers=headers,
    )
    assert bad.status_code == 422

    ok = await client.post(
        f"/projects/{project_id}/members",
        json={"user_id": users[0]["id"], "role_ids": [roles["VIEWER"]]},
        headers=headers,
    )
    assert ok.status_code == 201
    assert (await client.get(f"/projects/{project_id}", headers=await login("outsider"))).status_code == 200
