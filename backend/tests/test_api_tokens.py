from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.core.security import hash_api_token, new_api_token
from app.db.session import AsyncSessionLocal
from app.models import ApiToken


async def _create_token(client, login, username: str = "po.an", days: int = 30) -> dict:
    resp = await client.post(
        "/me/api-tokens",
        json={"name": "test", "expires_days": days},
        headers=await login(username),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_token_authenticates_and_is_shown_once(client, login):
    created = await _create_token(client, login)
    assert created["token"].startswith("pm_pat_")

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {created['token']}"})
    assert me.status_code == 200
    assert me.json()["username"] == "po.an"

    listed = await client.get("/me/api-tokens", headers=await login("po.an"))
    assert listed.status_code == 200
    assert all("token" not in item for item in listed.json())


async def test_revoked_token_is_rejected(client, login):
    created = await _create_token(client, login)
    headers = {"Authorization": f"Bearer {created['token']}"}
    assert (await client.get("/auth/me", headers=headers)).status_code == 200

    resp = await client.delete(f"/me/api-tokens/{created['id']}", headers=await login("po.an"))
    assert resp.status_code == 204
    assert (await client.get("/auth/me", headers=headers)).status_code == 401


async def test_expired_token_is_rejected(client, login):
    created = await _create_token(client, login)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ApiToken)
            .where(ApiToken.id == created["id"])
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await db.commit()

    resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {created['token']}"})
    assert resp.status_code == 401


async def test_unknown_token_is_rejected(client):
    assert (await client.get("/auth/me", headers={"Authorization": f"Bearer {new_api_token()}"})).status_code == 401


async def test_user_cannot_revoke_another_users_token(client, login):
    created = await _create_token(client, login, username="po.an")
    resp = await client.delete(f"/me/api-tokens/{created['id']}", headers=await login("sm.binh"))
    assert resp.status_code == 404


async def test_only_hash_is_stored(client, login):
    created = await _create_token(client, login)
    async with AsyncSessionLocal() as db:
        row = await db.get(ApiToken, created["id"])
    assert row.token_hash == hash_api_token(created["token"])
    assert created["token"] not in row.token_hash


async def test_executive_role_reads_all_projects_but_cannot_write(client, login):
    from app.cli import create_executive, issue_mcp_url

    await create_executive("exec.test", "exec.test@example.com", "Ban lãnh đạo test")
    connector_url = await issue_mcp_url("exec.test", days=30)
    token = connector_url.rsplit("/", 1)[1]
    headers = {"Authorization": f"Bearer {token}"}

    projects = await client.get("/projects", params={"size": 100}, headers=headers)
    assert projects.status_code == 200
    assert projects.json()["total"] >= 1  # xem tất cả dự án, không cần là thành viên

    some_project = projects.json()["items"][0]["id"]
    assert (await client.get(f"/projects/{some_project}/reports/summary", headers=headers)).status_code == 200
    assert (await client.get(f"/projects/{some_project}/requirements", headers=headers)).status_code == 200

    created = await client.post(
        "/projects",
        json={"key": "EXEC", "name": "Không được tạo"},
        headers=headers,
    )
    assert created.status_code == 403
