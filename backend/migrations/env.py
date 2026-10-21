"""Môi trường Alembic: engine async (asyncpg), URL lấy từ cấu hình ứng dụng."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401  — nạp toàn bộ model vào metadata cho autogenerate
from app.core.config import settings
from app.db.base import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    """Schema gốc viết bằng SQL (migrations/sql/), model chỉ khai báo phần ứng dụng cần: bảng, index,
    khoá ngoại, ràng buộc chỉ có trong DB thì autogenerate bỏ qua, không đề xuất DROP.
    Khoá ngoại không so sánh (model không khai báo ON DELETE / FK nhiều cột như SQL): tự viết trong migration."""
    if type_ == "foreign_key_constraint":
        return False
    return not (reflected and compare_to is None)


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(settings.database_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
