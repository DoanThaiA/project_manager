async def _create(client, headers, base, **body):
    resp = await client.post(f"{base}/work-items", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _status(client, headers, base, item_id):
    return (await client.get(f"{base}/work-items/{item_id}", headers=headers)).json()["status"]


async def test_subtasks_complete_parent(client, login, project_id):
    po = await login("po.an")
    base = f"/projects/{project_id}"

    req = (await client.post(f"{base}/requirements", json={"title": "Xuất hoá đơn"}, headers=po)).json()
    parent = await _create(client, po, base, title="Xuất hoá đơn điện tử", type="story", requirement_id=req["id"])
    sub1 = await _create(client, po, base, title="API tạo hoá đơn", parent_id=parent["id"])
    sub2 = await _create(client, po, base, title="Màn hình xem hoá đơn", parent_id=parent["id"], type="bug")
    sub3 = await _create(client, po, base, title="Gửi email", parent_id=parent["id"])

    # Loại luôn là subtask, kế thừa yêu cầu của cha
    assert sub2["type"] == "subtask" and sub1["requirement_id"] == req["id"]
    listed = (await client.get(f"{base}/work-items", params={"parent_id": parent["id"]}, headers=po)).json()
    assert [i["id"] for i in listed["items"]] == [sub1["id"], sub2["id"], sub3["id"]]

    # Subtask bắt đầu -> cha đang làm
    await client.patch(f"{base}/work-items/{sub1['id']}", json={"status": "in_progress"}, headers=po)
    assert await _status(client, po, base, parent["id"]) == "in_progress"

    # Còn subtask chưa xong -> không tự đánh dấu cha xong được
    resp = await client.patch(f"{base}/work-items/{parent['id']}", json={"status": "done"}, headers=po)
    assert resp.status_code == 409 and resp.json()["detail"].startswith("Còn 3 subtask chưa xong")

    for sub in (sub1, sub2):
        await client.patch(f"{base}/work-items/{sub['id']}", json={"status": "done"}, headers=po)
    assert await _status(client, po, base, parent["id"]) == "in_progress"
    counts = (await client.get(f"{base}/work-items/{parent['id']}", headers=po)).json()
    assert (counts["subtask_count"], counts["subtask_done"]) == (3, 2)

    # Subtask cuối bị huỷ: huỷ không tính, các subtask còn lại đã xong -> cha xong
    await client.patch(f"{base}/work-items/{sub3['id']}", json={"status": "cancelled"}, headers=po)
    done = (await client.get(f"{base}/work-items/{parent['id']}", headers=po)).json()
    assert done["status"] == "done" and done["completed_at"] is not None

    # Mở lại một subtask -> cha quay lại đang làm
    await client.patch(f"{base}/work-items/{sub2['id']}", json={"status": "testing"}, headers=po)
    assert await _status(client, po, base, parent["id"]) == "in_progress"

    # Thêm subtask mới vào cha đã xong -> cha mở lại
    await client.patch(f"{base}/work-items/{sub2['id']}", json={"status": "done"}, headers=po)
    assert await _status(client, po, base, parent["id"]) == "done"
    await _create(client, po, base, title="Ký số", parent_id=parent["id"])
    assert await _status(client, po, base, parent["id"]) == "in_progress"


async def test_subtask_rules(client, login, project_id):
    po = await login("po.an")
    base = f"/projects/{project_id}"
    parent = await _create(client, po, base, title="Cha")
    sub = await _create(client, po, base, title="Con", parent_id=parent["id"])
    other = await _create(client, po, base, title="Khác")

    # Không lồng nhiều cấp
    resp = await client.post(f"{base}/work-items", json={"title": "Cháu", "parent_id": sub["id"]}, headers=po)
    assert resp.status_code == 422
    resp = await client.patch(f"{base}/work-items/{parent['id']}", json={"parent_id": other["id"]}, headers=po)
    assert resp.status_code == 422

    # Gắn công việc có sẵn làm subtask -> đổi loại; gỡ ra -> về task
    moved = await client.patch(f"{base}/work-items/{other['id']}", json={"parent_id": parent["id"]}, headers=po)
    assert moved.json()["type"] == "subtask"
    freed = await client.patch(f"{base}/work-items/{other['id']}", json={"parent_id": None}, headers=po)
    assert freed.json()["type"] == "task" and freed.json()["parent_id"] is None

    # Xoá cha -> xoá luôn subtask
    assert (await client.delete(f"{base}/work-items/{parent['id']}", headers=po)).status_code == 204
    assert (await client.get(f"{base}/work-items/{sub['id']}", headers=po)).status_code == 404


async def test_subtasks_follow_parent_sprint(client, login, project_id):
    po, sm = await login("po.an"), await login("sm.binh")
    base = f"/projects/{project_id}"
    sprint = (
        await client.post(f"{base}/sprints", json={"start_date": "2026-12-01", "goal": "Subtask"}, headers=sm)
    ).json()

    parent = await _create(client, po, base, title="Đồng bộ kho", sprint_id=sprint["id"])
    sub = await _create(client, po, base, title="Bước 1", parent_id=parent["id"])
    finished = await _create(client, po, base, title="Bước 0", parent_id=parent["id"])
    assert sub["sprint_id"] == sprint["id"] and sub["status"] == "todo"
    await client.patch(f"{base}/work-items/{finished['id']}", json={"status": "done"}, headers=po)

    # Cha về backlog -> subtask chưa xong về theo, subtask đã xong ở lại sprint
    await client.patch(f"{base}/work-items/{parent['id']}", json={"sprint_id": None}, headers=po)
    sub_now = (await client.get(f"{base}/work-items/{sub['id']}", headers=po)).json()
    assert sub_now["sprint_id"] is None and sub_now["status"] == "backlog"
    finished_now = (await client.get(f"{base}/work-items/{finished['id']}", headers=po)).json()
    assert finished_now["sprint_id"] == sprint["id"]

    # Cha vào lại sprint -> subtask theo, backlog -> todo
    await client.patch(f"{base}/work-items/{parent['id']}", json={"sprint_id": sprint["id"]}, headers=po)
    sub_now = (await client.get(f"{base}/work-items/{sub['id']}", headers=po)).json()
    assert sub_now["sprint_id"] == sprint["id"] and sub_now["status"] == "todo"
