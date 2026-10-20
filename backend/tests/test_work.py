from datetime import date, timedelta


async def test_work_item_flow_updates_requirement(client, login, project_id):
    po, dev = await login("po.an"), await login("dev.cuong")
    base = f"/projects/{project_id}"

    req = (await client.post(f"{base}/requirements", json={"title": "Phân quyền kho"}, headers=po)).json()
    await client.post(f"{base}/requirements/{req['id']}/status", json={"status": "approved"}, headers=po)

    item = await client.post(
        f"{base}/work-items",
        json={
            "title": "API phân quyền kho",
            "type": "story",
            "requirement_id": req["id"],
            "sprint_id": 1,
            "story_points": 3,
            "original_estimate_hours": 10,
        },
        headers=dev,
    )
    assert item.status_code == 201, item.text
    item = item.json()
    assert item["code"] == "ERP-3"
    assert item["status"] == "todo" and float(item["remaining_hours"]) == 10

    resp = await client.patch(f"{base}/work-items/{item['id']}", json={"status": "in_progress"}, headers=dev)
    assert resp.status_code == 200
    req_now = (await client.get(f"{base}/requirements/{req['id']}", headers=dev)).json()
    assert req_now["status"] == "in_progress"

    done = (await client.patch(f"{base}/work-items/{item['id']}", json={"status": "done"}, headers=dev)).json()
    assert done["completed_at"] is not None and float(done["remaining_hours"]) == 0


async def test_dev_cannot_assign_to_others(client, login, project_id):
    resp = await client.post(
        f"/projects/{project_id}/work-items", json={"title": "x", "assignee_id": 5}, headers=await login("dev.cuong")
    )
    assert resp.status_code == 403


async def test_cross_project_sprint_rejected(client, login):
    headers = await login("po.an")
    crm = (await client.get("/projects", params={"q": "CRM"}, headers=headers)).json()["items"][0]
    resp = await client.post(f"/projects/{crm['id']}/work-items", json={"title": "x", "sprint_id": 1}, headers=headers)
    assert resp.status_code == 404


async def test_work_log_rules(client, login, project_id):
    dev, qa = await login("dev.cuong"), await login("qa.dung")
    url = f"/projects/{project_id}/work-logs"

    log = await client.post(
        url, json={"work_item_id": 2, "hours": 4, "description": "Viết API", "log_date": "2026-10-15"}, headers=dev
    )
    assert log.status_code == 201, log.text
    log = log.json()
    assert log["sprint_id"] == 1  # lấy từ công việc

    item = (await client.get(f"/projects/{project_id}/work-items/2", headers=dev)).json()
    assert float(item["remaining_hours"]) == 8  # 12 - 4

    over = await client.post(url, json={"hours": 21, "description": "x", "log_date": "2026-10-15"}, headers=dev)
    assert over.status_code == 422

    future = (date.today() + timedelta(days=1)).isoformat()
    assert (
        await client.post(url, json={"hours": 1, "description": "x", "log_date": future}, headers=dev)
    ).status_code == 422

    # Tester không sửa được log của dev; Scrum Master (work_log.manage) thì được
    assert (await client.patch(f"{url}/{log['id']}", json={"hours": 5}, headers=qa)).status_code == 403
    edited = await client.patch(f"{url}/{log['id']}", json={"hours": 5}, headers=await login("sm.binh"))
    assert edited.status_code == 200 and float(edited.json()["hours"]) == 5

    mine = (await client.get("/me/work-logs", params={"date_from": "2026-10-15"}, headers=dev)).json()
    assert mine["total"] == 1


async def test_reports(client, login, project_id):
    headers = await login("po.an")
    summary = (await client.get(f"/projects/{project_id}/reports/summary", headers=headers)).json()
    assert summary["active_sprint"]["name"] == "Sprint 1"
    assert summary["requirements_by_status"]["approved"] >= 1

    by_user = (
        await client.get(f"/projects/{project_id}/reports/work-logs", params={"group_by": "user"}, headers=headers)
    ).json()
    assert {r["label"]: float(r["total_hours"]) for r in by_user} == {"Phạm Văn Cường": 13.0}

    assert (
        await client.get(f"/projects/{project_id}/reports/summary", headers=await login("dev.cuong"))
    ).status_code == 403


async def test_sprint_lifecycle(client, login, project_id):
    sm = await login("sm.binh")
    base = f"/projects/{project_id}/sprints"

    s2 = await client.post(base, json={"start_date": "2026-10-27", "goal": "Báo cáo"}, headers=sm)
    assert s2.status_code == 201
    s2 = s2.json()
    assert s2["name"] == "Sprint 2" and s2["end_date"] == "2026-11-09"

    # Đang có Sprint 1 chạy -> không start được Sprint 2
    assert (await client.post(f"{base}/{s2['id']}/start", headers=sm)).status_code == 409

    done = await client.post(
        f"{base}/1/complete",
        json={"move_unfinished_to": "next_sprint", "next_sprint_id": s2["id"], "retrospective_note": "Ổn"},
        headers=sm,
    )
    assert done.status_code == 200 and done.json()["status"] == "completed"

    moved = (await client.get(f"/projects/{project_id}/work-items", params={"sprint_id": s2["id"]}, headers=sm)).json()
    assert {i["code"] for i in moved["items"]} == {"ERP-1", "ERP-2"}

    assert (await client.post(f"{base}/{s2['id']}/start", headers=sm)).json()["status"] == "active"
    progress = (await client.get(f"{base}/1/progress", headers=sm)).json()
    assert float(progress["completed_points"]) == 3
