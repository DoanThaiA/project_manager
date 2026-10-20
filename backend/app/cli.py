"""Lệnh quản trị chạy từ dòng lệnh.

    python -m app.cli create-admin --username admin --email admin@congty.vn --full-name "Quản trị viên"

Mật khẩu được hỏi qua prompt (không hiện trên màn hình), hoặc đọc từ stdin với --password-stdin.
Trong Docker: docker compose exec api python -m app.cli create-admin ...
"""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import or_, select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal, engine
from app.models import Role, User, UserRole
from app.models.enums import UserStatus


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Lệnh quản trị Project Manager")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="Tạo tài khoản quản trị hệ thống")
    admin.add_argument("--username", required=True)
    admin.add_argument("--email", required=True)
    admin.add_argument("--full-name", required=True)
    admin.add_argument("--password-stdin", action="store_true", help="Đọc mật khẩu từ stdin")
    args = parser.parse_args(argv)

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
