from collections.abc import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from app.core.config import settings

# pool_pre_ping: tự bỏ kết nối chết (DB restart) thay vì trả lỗi 500
engine = create_async_engine(settings.database_url, echo=settings.debug, pool_pre_ping=True)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


@event.listens_for(Session, "after_begin")
def _set_audit_context(session: Session, transaction, connection) -> None:
    """Mỗi khi một transaction bắt đầu, đẩy ngữ cảnh người thao tác xuống
    PostgreSQL (SET LOCAL) để trigger ghi activity_logs / status_history đúng người.
    Giá trị lấy từ session.info, do dependency get_current_user gán."""
    info = session.info
    if not info.get("user_id"):
        return
    connection.execute(
        text("SELECT set_config('app.current_user_id', :uid, true), set_config('app.client_ip', :ip, true)"),
        {"uid": str(info["user_id"]), "ip": info.get("client_ip") or ""},
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
