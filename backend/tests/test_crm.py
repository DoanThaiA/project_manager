def _email(message_id: str, **extra) -> dict:
    return {
        "email_message_id": message_id,
        "email_thread_id": f"thread-{message_id}",
        "received_at": "2026-10-30T09:15:00+07:00",
        "subject": "Xin báo giá túi giấy kraft",
        "content": "Chào anh/chị, bên em cần 5.000 túi giấy kraft size 20x30...",
        "customer_name": "Lê Thị Hoa",
        "customer_email": "Lê Thị Hoa <Hoa.Le@BanhNgon.vn>",
        "phone": "0903 111 222",
        "company": "",
        "inquiry_type": "bao_gia",
        "product_type": "Túi giấy kraft",
        "quantity": "5.000 cái",
        "summary": "Hỏi giá 5.000 túi kraft in logo",
        "ai_confidence": 0.92,
        **extra,
    }


async def test_ingest_groups_emails_by_sender(client, login, project_id):
    headers = await login("po.an")
    url = f"/projects/{project_id}/crm/emails/ingest"

    first = await client.post(url, json=_email("msg-001"), headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["created"] is True

    # n8n gửi lại cùng email -> không tạo mới
    again = await client.post(url, json=_email("msg-001", subject="khác"), headers=headers)
    assert again.json() == {**first.json(), "created": False}

    # Email thứ 2 của cùng khách: gộp vào khách cũ, chỉ điền trường còn trống, không ghi đè
    second = await client.post(
        url,
        json=_email(
            "msg-002",
            received_at="2026-10-31T08:00:00",
            customer_name="Hoa Lê",
            company="Tiệm bánh Ngon",
            inquiry_type="Đặt hàng",  # giá trị lạ -> khac
            ai_confidence="",
        ),
        headers=headers,
    )
    assert second.json()["created"] is True
    contact_id = first.json()["contact_id"]
    assert second.json()["contact_id"] == contact_id

    contact = (await client.get(f"/projects/{project_id}/crm/contacts/{contact_id}", headers=headers)).json()
    assert contact["email"] == "hoa.le@banhngon.vn"
    assert contact["full_name"] == "Lê Thị Hoa"
    assert contact["company"] == "Tiệm bánh Ngon"
    assert contact["status"] == "new"
    assert contact["email_count"] == 2
    assert contact["last_inquiry_type"] == "khac"
    assert contact["last_contact_at"].startswith("2026-10-31T08:00:00")

    emails = (
        await client.get(f"/projects/{project_id}/crm/emails", params={"contact_id": contact_id}, headers=headers)
    ).json()
    assert [e["email_message_id"] for e in emails["items"]] == ["msg-002", "msg-001"]
    assert emails["items"][1]["ai_confidence"] == "0.92"
    assert emails["items"][0]["ai_confidence"] is None


async def test_track_contact_status_and_assignee(client, login, project_id):
    headers = await login("po.an")
    base = f"/projects/{project_id}/crm"
    contact_id = (
        await client.post(
            f"{base}/emails/ingest", json=_email("msg-101", customer_email="minh@abc.vn"), headers=headers
        )
    ).json()["contact_id"]

    members = (await client.get(f"/projects/{project_id}/members", headers=headers)).json()
    sm_id = next(m["user"]["id"] for m in members if m["user"]["username"] == "sm.binh")
    resp = await client.patch(
        f"{base}/contacts/{contact_id}",
        json={"status": "quoted", "assignee_id": sm_id, "note": "Đã gửi báo giá qua email"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert (resp.json()["status"], resp.json()["assignee_id"]) == ("quoted", sm_id)

    admin_id = (await client.get("/auth/me", headers=await login("admin"))).json()["id"]
    not_member = await client.patch(f"{base}/contacts/{contact_id}", json={"assignee_id": admin_id}, headers=headers)
    assert not_member.status_code == 422
    empty = await client.patch(f"{base}/contacts/{contact_id}", json={"status": None}, headers=headers)
    assert empty.status_code == 422

    listed = (await client.get(f"{base}/contacts", params={"status": "quoted"}, headers=headers)).json()
    assert [c["id"] for c in listed["items"]] == [contact_id]

    stats = (await client.get(f"{base}/stats", headers=headers)).json()
    assert stats["by_status"]["quoted"] == 1
    assert stats["total"] == sum(stats["by_status"].values())

    logs = (
        await client.get(
            f"/projects/{project_id}/activity-logs", params={"entity_type": "crm_contacts"}, headers=headers
        )
    ).json()
    assert any(log["action"] == "status_change" and log["entity_id"] == contact_id for log in logs["items"])


async def test_manual_contact_and_delete(client, login, project_id):
    headers = await login("po.an")
    base = f"/projects/{project_id}/crm"
    created = await client.post(
        f"{base}/contacts", json={"email": "Lan@Shop.vn", "full_name": "Chị Lan", "phone": "0988"}, headers=headers
    )
    assert created.status_code == 201, created.text
    assert (created.json()["source"], created.json()["email_count"]) == ("manual", 0)

    dup = await client.post(f"{base}/contacts", json={"email": "lan@shop.vn"}, headers=headers)
    assert dup.status_code == 409

    # Email đến sau gộp vào khách nhập tay, không ghi đè tên đã nhập
    ingest = await client.post(
        f"{base}/emails/ingest", json=_email("msg-201", customer_email="lan@shop.vn"), headers=headers
    )
    contact_id = created.json()["id"]
    assert ingest.json()["contact_id"] == contact_id
    contact = (await client.get(f"{base}/contacts/{contact_id}", headers=headers)).json()
    assert (contact["full_name"], contact["email_count"]) == ("Chị Lan", 1)

    assert (await client.delete(f"{base}/contacts/{contact_id}", headers=headers)).status_code == 204
    assert (await client.get(f"{base}/contacts/{contact_id}", headers=headers)).status_code == 404
    lead = await client.get(f"{base}/emails/{ingest.json()['lead_id']}", headers=headers)
    assert lead.status_code == 404


async def test_crm_permissions(client, login, project_id):
    base = f"/projects/{project_id}/crm"
    dev = await login("dev.cuong")
    customer = await login("kh.abc")
    assert (await client.get(f"{base}/contacts", headers=dev)).status_code == 403
    assert (await client.get(f"{base}/contacts", headers=customer)).status_code == 403
    assert (await client.post(f"{base}/emails/ingest", json=_email("msg-301"), headers=dev)).status_code == 403

    sm = await login("sm.binh")  # Scrum Master chỉ xem
    assert (await client.get(f"{base}/contacts", headers=sm)).status_code == 200
    assert (await client.post(f"{base}/contacts", json={"email": "x@y.vn"}, headers=sm)).status_code == 403
