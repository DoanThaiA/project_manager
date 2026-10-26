# Chạy sau test_requirements.py (thứ tự file) để không làm lệch mã yêu cầu tự sinh mà file đó kiểm tra
PDF = b"%PDF-1.7\n" + b"x" * 100


async def test_customer_attaches_files_to_own_requirement(client, login, project_id, fake_r2):
    customer = await login("kh.abc")
    own = (
        await client.post(f"/projects/{project_id}/requirements", json={"title": "Thêm báo cáo"}, headers=customer)
    ).json()
    own_url = f"/projects/{project_id}/requirements/{own['id']}/files"
    up = await client.post(own_url, files={"file": ("mau.pdf", PDF, "application/pdf")}, headers=customer)
    assert up.status_code == 201, up.text
    assert (await client.delete(f"{own_url}/{up.json()['id']}", headers=customer)).status_code == 204
    assert fake_r2 == {}

    # Yêu cầu của người khác (không có quyền sửa) -> 403
    other = f"/projects/{project_id}/requirements/1/files"
    resp = await client.post(other, files={"file": ("x.pdf", PDF, "application/pdf")}, headers=customer)
    assert resp.status_code == 403
