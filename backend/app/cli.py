"""Lệnh quản trị chạy từ dòng lệnh.

    python -m app.cli create-admin --username admin --email admin@congty.vn --full-name "Quản trị viên"

Mật khẩu được hỏi qua prompt (không hiện trên màn hình), hoặc đọc từ stdin với --password-stdin.
Trong Docker: docker compose exec api python -m app.cli create-admin ...
"""

import argparse
import asyncio
import getpass
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update

from app.core.config import settings
from app.core.security import hash_api_token, hash_password, new_api_token
from app.db.session import AsyncSessionLocal, engine
from app.models import ApiToken, Role, User, UserRole
from app.models.enums import UserStatus

# Tên token dùng cho connector MCP; cấp lại sẽ thu hồi token cũ cùng tên
MCP_TOKEN_NAME = "mcp-connector"


async def create_admin(username: str, email: str, full_name: str, password: str) -> User:
    """Tạo tài khoản quản trị hệ thống; lỗi nếu username/email đã tồn tại."""
    if len(password) < 8:
        raise ValueError("Mật khẩu tối thiểu 8 ký tự")
    async with AsyncSessionLocal() as db:
        exists = await db.scalar(select(User.id).where(or_(User.username == username, User.email == email)))
        if exists:
            raise ValueError(f"Username hoặc email đã tồn tại (user id={exists})")
        user = User(
            username=username,
            email=email,
            full_name=full_name,
            password_hash=hash_password(password),
            is_system_admin=True,
            status=UserStatus.active,
        )
        db.add(user)
        await db.flush()
        role_id = await db.scalar(select(Role.id).where(Role.code == "SYSTEM_ADMIN"))
        if role_id:
            db.add(UserRole(user_id=user.id, role_id=role_id))
        await db.commit()
        return user


async def create_executive(username: str, email: str, full_name: str) -> str:
    """Tài khoản ban lãnh đạo: vai trò EXECUTIVE (chỉ đọc). Không đặt mật khẩu, dùng qua connector MCP."""
    async with AsyncSessionLocal() as db:
        exists = await db.scalar(select(User.id).where(or_(User.username == username, User.email == email)))
        if exists:
            raise ValueError(f"Username hoặc email đã tồn tại (user id={exists})")
        user = User(username=username, email=email, full_name=full_name, status=UserStatus.active)
        db.add(user)
        await db.flush()
        role_id = await db.scalar(select(Role.id).where(Role.code == "EXECUTIVE"))
        if role_id is None:
            raise ValueError("Chưa có vai trò EXECUTIVE — chạy migration 0011 trước")
        db.add(UserRole(user_id=user.id, role_id=role_id))
        await db.commit()
        return f"Đã tạo tài khoản ban lãnh đạo '{user.username}' (id={user.id})"


async def issue_mcp_url(username: str, days: int) -> str:
    """Cấp URL connector MCP mới cho user; token cũ (cùng tên) bị thu hồi ngay."""
    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == username, User.deleted_at.is_(None)))
        if user is None:
            raise ValueError(f"Không có user '{username}'")
        now = datetime.now(UTC)
        await db.execute(
            update(ApiToken)
            .where(ApiToken.user_id == user.id, ApiToken.name == MCP_TOKEN_NAME, ApiToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        token = new_api_token()
        db.add(
            ApiToken(
                user_id=user.id,
                name=MCP_TOKEN_NAME,
                token_hash=hash_api_token(token),
                expires_at=now + timedelta(days=days),
            )
        )
        await db.commit()
    return f"{settings.mcp_public_base_url.rstrip('/')}/mcp/{token}"


async def revoke_mcp_url(username: str) -> str:
    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == username))
        if user is None:
            raise ValueError(f"Không có user '{username}'")
        result = await db.execute(
            update(ApiToken)
            .where(ApiToken.user_id == user.id, ApiToken.name == MCP_TOKEN_NAME, ApiToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await db.commit()
        return f"Đã thu hồi {result.rowcount} URL connector của '{username}'"


def _run_simple(coro) -> int:
    """Chạy một lệnh async, in kết quả (chuỗi); ValueError thì in lỗi và trả mã 1."""

    async def wrapped():
        try:
            return await coro
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(wrapped())
    except ValueError as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        return 1
    print(result)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Lệnh quản trị Project Manager")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="Tạo tài khoản quản trị hệ thống")
    admin.add_argument("--username", required=True)
    admin.add_argument("--email", required=True)
    admin.add_argument("--full-name", required=True)
    admin.add_argument("--password-stdin", action="store_true", help="Đọc mật khẩu từ stdin")

    exe = sub.add_parser("create-executive", help="Tạo tài khoản ban lãnh đạo (chỉ đọc, dùng qua connector MCP)")
    exe.add_argument("--username", required=True)
    exe.add_argument("--email", required=True)
    exe.add_argument("--full-name", required=True)

    issue = sub.add_parser("issue-mcp-url", help="Cấp URL connector MCP (thu hồi URL cũ của user)")
    issue.add_argument("--username", required=True)
    issue.add_argument("--days", type=int, default=180, help="Hạn token, tối đa 365 ngày")

    revoke = sub.add_parser("revoke-mcp-url", help="Thu hồi URL connector MCP của user")
    revoke.add_argument("--username", required=True)

    args = parser.parse_args(argv)

    if args.command == "create-executive":
        return _run_simple(create_executive(args.username, args.email, args.full_name))
    if args.command == "issue-mcp-url":
        if not 1 <= args.days <= 365:
            print("Lỗi: --days phải từ 1 đến 365", file=sys.stderr)
            return 1
        return _run_simple(issue_mcp_url(args.username, args.days))
    if args.command == "revoke-mcp-url":
        return _run_simple(revoke_mcp_url(args.username))

    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("Mật khẩu: ")
        if password != getpass.getpass("Nhập lại mật khẩu: "):
            print("Mật khẩu không khớp", file=sys.stderr)
            return 1

    async def run() -> User:
        try:
            return await create_admin(args.username, args.email, args.full_name, password)
        finally:
            await engine.dispose()

    try:
        user = asyncio.run(run())
    except ValueError as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        return 1
    print(f"Đã tạo quản trị viên '{user.username}' (id={user.id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
