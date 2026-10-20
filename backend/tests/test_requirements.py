async def _create(client, headers, project_id, **extra) -> dict:
    resp = await client.post(
        f"/projects/{project_id}/requirements",
        json={"title": "Xuất hoá đơn điện tử", "priority": "high", "type": "feature", **extra},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_customer_creates_requirement_with_generated_code(client, login, project_id):
    req = await _create(client, await login("kh.abc"), project_id, source="ticket")
    assert req["code"] == "ERP-REQ-0003"
    assert req["status"] == "new"
    assert req["customer_id"] is not None  # trigger lấy từ dự án


async def test_status_flow_and_approval_permission(client, login, project_id):
    po, dev = await login("po.an"), await login("dev.cuong")
    req = await _create(client, po, project_id)
    url = f"/projects/{project_id}/requirements/{req['id']}"

    # Dev không có quyền cập nhật / duyệt
    assert (await client.post(f"{url}/status", json={"status": "approved"}, headers=dev)).status_code == 403

    # Luồng không hợp lệ
    bad = await client.post(f"{url}/status", json={"status": "done"}, headers=po)
    assert bad.status_code == 409

    # Từ chối phải có lý do
    assert (await client.post(f"{url}/status", json={"status": "rejected"}, headers=po)).status_code == 422

    ok = await client.post(f"{url}/status", json={"status": "approved", "note": "KH chốt qua email"}, headers=po)
    assert ok.status_code == 200
    assert ok.json()["approved_at"] is not None and ok.json()["approved_by"] is not None

    history = (await client.get(f"{url}/history", headers=po)).json()
    assert [(h["from_status"], h["to_status"]) for h in history] == [(None, "new"), ("new", "approved")]
    assert history[1]["note"] == "KH chốt qua email"
    assert history[1]["changed_by_name"] == "Trần Văn An"

    activity = (await client.get(f"{url}/activity", headers=po)).json()
    assert activity["items"][0]["action"] == "status_change"
    assert activity["items"][0]["actor_name"] == "Trần Văn An"


async def test_list_filters_and_search(client, login, project_id):
    headers = await login("po.an")
    resp = await client.get(
        f"/projects/{project_id}/requirements",
        params={"status": ["approved"], "q": "nhập kho", "sort": "-priority"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert [r["code"] for r in resp.json()["items"]] == ["ERP-REQ-0001"]

    bad_sort = await client.get(f"/projects/{project_id}/requirements", params={"sort": "abc"}, headers=headers)
    assert bad_sort.status_code == 422


async def test_assignee_must_be_member(client, login, project_id):
    resp = await client.post(
        f"/projects/{project_id}/requirements",
        json={"title": "x", "assignee_id": 999999},
        headers=await login("po.an"),
    )
    assert resp.status_code == 422


async def test_internal_comments_hidden_from_customer(client, login, project_id):
    po, customer = await login("po.an"), await login("kh.abc")
    url = f"/projects/{project_id}/requirements/1/comments"

    assert (
        await client.post(url, json={"content": "Ước lượng 3 ngày", "is_internal": True}, headers=po)
    ).status_code == 201
    assert (await client.post(url, json={"content": "Khi nào xong ạ?"}, headers=customer)).status_code == 201
    forbidden = await client.post(url, json={"content": "x", "is_internal": True}, headers=customer)
    assert forbidden.status_code == 403

    seen_by_po = [c["content"] for c in (await client.get(url, headers=po)).json()]
    seen_by_customer = [c["content"] for c in (await client.get(url, headers=customer)).json()]
    assert seen_by_po == ["Ước lượng 3 ngày", "Khi nào xong ạ?"]
    assert seen_by_customer == ["Khi nào xong ạ?"]


async def test_requirement_detail_stats(client, login, project_id):
    resp = await client.get(f"/projects/{project_id}/requirements/1", headers=await login("dev.cuong"))
    assert resp.status_code == 200
    stats = resp.json()["stats"]
    assert stats["work_item_count"] == 2
    assert float(stats["logged_hours"]) == 6.0
