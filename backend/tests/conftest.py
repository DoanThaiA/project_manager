"""Test tích hợp trên PostgreSQL thật.

Mỗi lần chạy: tạo lại database `project_manager_test` bằng Alembic (upgrade head) + db/seeds, trên cùng
server với DATABASE_URL (PostgreSQL dùng chung với ai_carbon_analyst; pm_user có quyền CREATEDB).
Tài khoản mẫu: mật khẩu Demo@123.
"""

import asyncio
import os
from pathlib import Path
from urllib.parse import quote

import asyncpg
import pytest
from dotenv import dotenv_values
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url

# KHÔNG import app.* ở đầu file: app.core.config đọc .env (database dev) ngay khi import.
# Phải đặt DATABASE_URL trỏ vào database test TRƯỚC khi app được import lần đầu.
BACKEND = Path(__file__).resolve().parents[1]
TEST_DB = "project_manager_test"


def _server_dsn() -> str:
    """DSN của server (không kèm tên database): TEST_PG_DSN, hoặc suy ra từ DATABASE_URL (.env)."""
    if dsn := os.environ.get("TEST_PG_DSN"):
        return dsn
    raw = os.environ.get("DATABASE_URL") or dotenv_values(BACKEND / ".env").get("DATABASE_URL")
    if not raw:
        raise RuntimeError("Đặt TEST_PG_DSN hoặc DATABASE_URL (backend/.env) để chạy test")
    url = make_url(raw)
    return f"postgresql://{quote(url.username or '')}:{quote(url.password or '')}@{url.host}:{url.port or 5432}"


PG_DSN = _server_dsn()
os.environ["DATABASE_URL"] = PG_DSN.replace("postgresql://", "postgresql+asyncpg://") + f"/{TEST_DB}"

DEMO_SEED = BACKEND.parent / "db/seeds/02_demo_data.sql"
PASSWORD = "Demo@123"


@pytest.fixture(scope="session", autouse=True)
async def database():
    admin = await asyncpg.connect(f"{PG_DSN}/postgres")
    await admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    await admin.execute(f"CREATE DATABASE {TEST_DB}")
    await admin.execute(f"ALTER DATABASE {TEST_DB} SET timezone TO 'Asia/Ho_Chi_Minh'")
    await admin.close()

    from alembic import command
    from alembic.config import Config

    # env.py tự gọi asyncio.run -> chạy trong thread riêng để không đụng event loop của pytest
    await asyncio.to_thread(command.upgrade, Config(BACKEND / "alembic.ini"), "head")

    conn = await asyncpg.connect(f"{PG_DSN}/{TEST_DB}")
    await conn.execute(DEMO_SEED.read_text())
    await conn.close()
    yield


@pytest.fixture(scope="session")
async def client(database):
    from app.db.session import engine
    from app.main import app

    # Chốt an toàn: không bao giờ chạy test trên database dev/production
    assert engine.url.database == TEST_DB, f"Test đang trỏ vào database '{engine.url.database}', dừng lại!"

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


@pytest.fixture
def fake_r2(monkeypatch):
    """Thay Cloudflare R2 bằng dict trong bộ nhớ."""
    from app.services import file_storage

    objects: dict[str, tuple[bytes, str]] = {}

    async def upload(key, data, size, content_type):
        content = data.read()
        assert len(content) == size
        objects[key] = (content, content_type)

    async def delete(key):
        objects.pop(key, None)

    monkeypatch.setattr(file_storage, "upload", upload)
    monkeypatch.setattr(file_storage, "delete", delete)
    monkeypatch.setattr(file_storage, "download_url", lambda key, name: f"https://r2.test/bucket/{key}")
    monkeypatch.setattr(file_storage, "preview_url", lambda key, name, kind: f"https://r2.test/view/{key}")
    return objects
