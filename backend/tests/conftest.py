"""Test tích hợp trên PostgreSQL thật.

Mỗi lần chạy: tạo lại database `project_manager_test` từ db/migrations + db/seeds
(cùng server với docker-compose, cổng 5435). Tài khoản mẫu: mật khẩu Demo@123.
"""

import os
from pathlib import Path

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

PG_DSN = os.environ.get("TEST_PG_DSN", "postgresql://pm_user:pm_password@localhost:5435")
TEST_DB = "project_manager_test"
os.environ["DATABASE_URL"] = PG_DSN.replace("postgresql://", "postgresql+asyncpg://") + f"/{TEST_DB}"

ROOT = Path(__file__).resolve().parents[2]
SQL_FILES = [
    ROOT / "db/migrations/V1__init_schema.sql",
    ROOT / "db/seeds/01_roles_permissions.sql",
    ROOT / "db/seeds/02_demo_data.sql",
]
PASSWORD = "Demo@123"


@pytest.fixture(scope="session", autouse=True)
async def database():
    admin = await asyncpg.connect(f"{PG_DSN}/postgres")
    await admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    await admin.execute(f"CREATE DATABASE {TEST_DB}")
    await admin.close()

    conn = await asyncpg.connect(f"{PG_DSN}/{TEST_DB}")
    for path in SQL_FILES:
        await conn.execute(path.read_text())
    await conn.close()
    yield


@pytest.fixture(scope="session")
async def client(database):
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api/v1") as c:
        yield c


@pytest.fixture(scope="session")
async def login(client):
    cache: dict[str, dict[str, str]] = {}

    async def _login(username: str) -> dict[str, str]:
        if username not in cache:
            resp = await client.post("/auth/login", data={"username": username, "password": PASSWORD})
            assert resp.status_code == 200, resp.text
            cache[username] = {"Authorization": f"Bearer {resp.json()['access_token']}"}
        return cache[username]

    return _login


@pytest.fixture(scope="session")
async def project_id(client, login) -> int:
    resp = await client.get("/projects", params={"q": "ERP"}, headers=await login("admin"))
    return resp.json()["items"][0]["id"]
