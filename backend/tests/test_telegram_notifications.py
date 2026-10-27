from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import delete, select, text, update

PRIVATE_CHAT = 1001
GROUP_CHAT = -2002


@pytest.fixture(scope="module")
async def project_id(client) -> int:
    """Dự án riêng: không làm lệch mã công việc / sprint của dự án ERP mà các test khác dùng."""
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        pid = await db.scalar(text("INSERT INTO projects (key, name) VALUES ('TGN', 'Dự án thông báo') RETURNING id"))
        await db.execute(
            text("""
            INSERT INTO project_members (project_id, user_id, role_id)
            SELECT :pid, u.id, r.id
              FROM (VALUES ('po.an', 'PRODUCT_OWNER'), ('sm.binh', 'SCRUM_MASTER'),
                           ('dev.cuong', 'DEVELOPER'), ('qa.dung', 'TESTER')) AS m(username, role_code)
              JOIN users u ON u.username = m.username
              JOIN roles r ON r.code = m.role_code
            """),
            {"pid": pid},
        )
        await db.execute(
            text("""
            INSERT INTO sprints (project_id, sprint_no, name, start_date, end_date, status)
            VALUES (:pid, 1, 'Sprint 1', current_date, current_date + 13, 'active')
            """),
            {"pid": pid},
        )
        await db.commit()
    return pid


@pytest.fixture
async def tg(monkeypatch):
    """Thay Telegram bằng danh sách tin đã gửi trong bộ nhớ; dọn chat / hàng đợi sau mỗi test."""
    from app.core.config import settings
    from app.db.session import AsyncSessionLocal
    from app.models import NotificationDelivery, TelegramChat
    from app.services.notifications import telegram
    from app.services.notifications.producer import produce

    sent: list[tuple[int, str]] = []
    state = {"error": None}

    async def send_message(chat_id, html):
        if state["error"]:
            raise state["error"]
        sent.append((chat_id, html))

    async def bot_username():
        return "pm_test_bot"

    monkeypatch.setattr(settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(settings, "app_public_url", "https://dev.mcv.network")
    monkeypatch.setattr(telegram, "send_message", send_message)
    monkeypatch.setattr(telegram, "bot_username", bot_username)

    async with AsyncSessionLocal() as db:
        while await produce(db):  # bỏ sự kiện của các test trước
            pass
        await db.execute(delete(NotificationDelivery))
        await db.commit()

    yield {"sent": sent, "state": state}

    async with AsyncSessionLocal() as db:
        await db.execute(delete(TelegramChat))
        await db.execute(text("DELETE FROM notification_events"))
        await db.commit()


async def bot_receives(chat: dict, message_text: str) -> None:
    from app.db.session import AsyncSessionLocal
    from app.services.notifications.bot import handle_update

    async with AsyncSessionLocal() as db:
        await handle_update(db, {"update_id": 1, "message": {"chat": chat, "text": message_text}})


async def run_worker() -> None:
    from app.db.session import AsyncSessionLocal
    from app.services.notifications.producer import produce
    from app.services.notifications.sender import send_due

    async with AsyncSessionLocal() as db:
        while await produce(db):
            pass
        while await send_due(db):
            pass


def code_of(url: str) -> str:
    return url.rsplit("=", 1)[1]


async def link_chats(client, login, project_id):
    """dev.cuong kết nối Telegram cá nhân, po.an thêm bot vào group của dự án."""
    dev = await login("dev.cuong")
    me = await client.post("/me/telegram/link", headers=dev)
    assert me.status_code == 200, me.text
    assert me.json()["url"].startswith("https://t.me/pm_test_bot?start=")
    await bot_receives(
        {"id": PRIVATE_CHAT, "type": "private", "first_name": "Cường"}, f"/start {code_of(me.json()['url'])}"
    )

    po = await login("po.an")
    group = await client.post(f"/projects/{project_id}/telegram/link", headers=po)
    assert group.status_code == 200, group.text
    assert "?startgroup=" in group.json()["url"]
    await bot_receives(
        {"id": GROUP_CHAT, "type": "group", "title": "ERP team"}, f"/start@pm_test_bot {code_of(group.json()['url'])}"
    )


async def new_item(client, login, project_id, title="Việc test thông báo") -> dict:
    from app.db.session import AsyncSessionLocal
    from app.models import Sprint, User

    async with AsyncSessionLocal() as db:
        dev_id = await db.scalar(select(User.id).where(User.username == "dev.cuong"))
        sprint_id = await db.scalar(select(Sprint.id).where(Sprint.project_id == project_id, Sprint.sprint_no == 1))
    resp = await client.post(
        f"/projects/{project_id}/work-items",
        json={"title": title, "assignee_ids": [dev_id], "sprint_id": sprint_id, "status": "todo"},
        headers=await login("po.an"),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def set_status(client, login, project_id, item_id, status, user="qa.dung"):
    resp = await client.patch(
        f"/projects/{project_id}/work-items/{item_id}", json={"status": status}, headers=await login(user)
    )
    assert resp.status_code == 200, resp.text


async def test_link_and_notify_status_change(client, login, project_id, tg):
    await link_chats(client, login, project_id)
    replies = dict(tg["sent"])
    assert "Đã kết nối" in replies[PRIVATE_CHAT] and "Phạm Văn Cường" in replies[PRIVATE_CHAT]
    assert "TGN · Dự án thông báo" in replies[GROUP_CHAT]
    tg["sent"].clear()

    me = (await client.get("/me/telegram", headers=await login("dev.cuong"))).json()
    assert me["configured"] and me["chat"]["title"] == "Cường"
    assert me["chat"]["subscriptions"] == [
        {"event": "work_item.status_changed", "scope": "mine", "statuses": [], "enabled": True}
    ]

    item = await new_item(client, login, project_id)
    await set_status(client, login, project_id, item["id"], "in_progress")
    await run_worker()

    sent = dict(tg["sent"])
    assert set(sent) == {PRIVATE_CHAT, GROUP_CHAT}  # việc giao cho dev.cuong, qa.dung là người đổi
    msg = sent[GROUP_CHAT]
    assert item["code"] in msg and "Cần làm → <b>Đang làm</b>" in msg
    assert "Hoàng Thị Dung đã chuyển" in msg and "Giao cho: Phạm Văn Cường" in msg
    assert f'href="https://dev.mcv.network/projects/{project_id}/board?item={item["id"]}"' in msg


async def test_actor_and_status_filter(client, login, project_id, tg):
    await link_chats(client, login, project_id)
    tg["sent"].clear()
    item = await new_item(client, login, project_id)

    # Người được giao tự đổi trạng thái -> không báo cho chính họ, group vẫn nhận
    await set_status(client, login, project_id, item["id"], "in_progress", user="dev.cuong")
    await run_worker()
    assert [c for c, _ in tg["sent"]] == [GROUP_CHAT]
    tg["sent"].clear()

    # Group chỉ nhận khi chuyển sang "done"
    po = await login("po.an")
    chat_id = (await client.get(f"/projects/{project_id}/telegram", headers=po)).json()["chats"][0]["id"]
    resp = await client.put(
        f"/projects/{project_id}/telegram/chats/{chat_id}/subscriptions/work_item.status_changed",
        json={"statuses": ["done"]},
        headers=po,
    )
    assert resp.status_code == 200 and resp.json()["statuses"] == ["done"]
    await set_status(client, login, project_id, item["id"], "in_review")
    await run_worker()
    assert [c for c, _ in tg["sent"]] == [PRIVATE_CHAT]
    tg["sent"].clear()
    await set_status(client, login, project_id, item["id"], "done")
    await run_worker()
    assert sorted(c for c, _ in tg["sent"]) == [GROUP_CHAT, PRIVATE_CHAT]


async def test_bulk_change_is_one_message(client, login, project_id, tg):
    from app.db.session import AsyncSessionLocal
    from app.models import User, WorkItem

    await link_chats(client, login, project_id)
    tg["sent"].clear()
    a = await new_item(client, login, project_id, "Việc A <b>")
    b = await new_item(client, login, project_id, "Việc B")

    # Như kết thúc sprint: nhiều công việc đổi trạng thái trong một transaction
    async with AsyncSessionLocal() as db:
        sm = await db.scalar(select(User.id).where(User.username == "sm.binh"))
        await db.execute(text("SELECT set_config('app.current_user_id', :u, true)"), {"u": str(sm)})
        await db.execute(update(WorkItem).where(WorkItem.id.in_([a["id"], b["id"]])).values(status="backlog"))
        await db.commit()
    await run_worker()

    group = [m for c, m in tg["sent"] if c == GROUP_CHAT]
    assert len(group) == 1
    assert "Lê Thị Bình</b> đã chuyển trạng thái 2 công việc" in group[0]
    assert "Việc A &lt;b&gt;" in group[0]  # tiêu đề được escape


async def test_delivery_errors(client, login, project_id, tg):
    from app.db.session import AsyncSessionLocal
    from app.models import NotificationDelivery, TelegramChat
    from app.services.notifications.telegram import TelegramError

    await link_chats(client, login, project_id)
    item = await new_item(client, login, project_id)

    tg["state"]["error"] = httpx.ConnectError("mạng lỗi")
    await set_status(client, login, project_id, item["id"], "in_progress")
    await run_worker()
    async with AsyncSessionLocal() as db:
        rows = list(await db.scalars(select(NotificationDelivery)))
        assert len(rows) == 2 and all(r.status == "pending" and r.attempts == 1 for r in rows)
        assert all(r.next_try_at > datetime.now(UTC) + timedelta(seconds=20) for r in rows)

        # Bot bị đuổi khỏi group -> group ngừng nhận; tin cá nhân bị giới hạn tốc độ -> chờ, không tính lỗi
        await db.execute(update(NotificationDelivery).values(next_try_at=datetime.now(UTC)))
        await db.commit()

    async def send_message(chat_id, html):
        if chat_id == GROUP_CHAT:
            raise TelegramError(403, "Forbidden: bot was kicked from the group chat")
        raise TelegramError(429, "Too Many Requests", {"retry_after": 7})

    from app.services.notifications import telegram

    tg["state"]["error"] = None
    original = telegram.send_message
    telegram.send_message = send_message
    try:
        await run_worker()
    finally:
        telegram.send_message = original

    async with AsyncSessionLocal() as db:
        group = await db.scalar(select(TelegramChat).where(TelegramChat.chat_id == GROUP_CHAT))
        assert group.is_active is False
        by_chat = {r.telegram_chat_id: r for r in await db.scalars(select(NotificationDelivery))}
        assert by_chat[group.id].status == "failed"
        private = next(r for k, r in by_chat.items() if k != group.id)
        assert private.status == "pending" and private.attempts == 1


async def test_invalid_code_and_permissions(client, login, project_id, tg):
    await bot_receives({"id": PRIVATE_CHAT, "type": "private"}, "/start khong-co-ma")
    assert "không hợp lệ" in tg["sent"][-1][1]

    # Link cá nhân mở trong group -> từ chối
    url = (await client.post("/me/telegram/link", headers=await login("qa.dung"))).json()["url"]
    await bot_receives({"id": GROUP_CHAT, "type": "group", "title": "x"}, f"/start {code_of(url)}")
    assert "chat riêng" in tg["sent"][-1][1]

    dev = await login("dev.cuong")
    assert (await client.get(f"/projects/{project_id}/telegram", headers=dev)).status_code == 403
    assert (await client.post(f"/projects/{project_id}/telegram/link", headers=dev)).status_code == 403
    assert (await client.get(f"/projects/{project_id}/telegram", headers=await login("sm.binh"))).status_code == 200
