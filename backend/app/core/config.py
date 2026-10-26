from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Project Manager API"
    environment: str = "development"
    debug: bool = False

    # Server PostgreSQL dùng chung với ai_carbon_analyst (cổng 5433, chỉ localhost); mật khẩu đặt qua .env
    database_url: str = "postgresql+asyncpg://pm_user:CHANGE_ME@localhost:5433/project_manager"

    secret_key: str = "change-me-to-a-random-64-char-secret"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 8

    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Cloudflare Images lưu ảnh đính kèm công việc
    cf_account_id: str = ""
    cf_images_token: str = ""  # API token quyền "Cloudflare Images: Edit"
    cf_images_account_hash: str = ""  # trong Dashboard › Images (URL imagedelivery.net/<hash>/...)
    cf_images_variant: str = "public"
    # Có signing key: ảnh riêng tư, hiển thị qua URL ký tạm hết hạn sau cf_images_url_expire_seconds.
    # Bỏ trống: ảnh public, ai có link đều xem được.
    cf_images_signing_key: str = ""
    cf_images_url_expire_seconds: int = 60 * 60
    attachment_max_mb: int = 10

    # Cloudflare R2 lưu file đính kèm (tài liệu, PDF, Excel, zip...); bucket phải có sẵn, để private
    r2_account_id: str = ""
    r2_access_key_id: str = ""  # R2 › Manage API tokens › quyền "Object Read & Write" trên bucket
    r2_secret_access_key: str = ""
    r2_bucket: str = "project-manager"
    # Bỏ trống = <account_id>.r2.cloudflarestorage.com; bucket ở EU: <account_id>.eu.r2.cloudflarestorage.com
    r2_endpoint: str = ""
    file_max_mb: int = 50
    file_url_expire_seconds: int = 60 * 60
    # Xem trước Word / Excel / PowerPoint qua Microsoft Office Online: Microsoft tải file qua link ký tạm.
    # Tắt nếu tài liệu không được phép gửi ra ngoài (khi đó các file này chỉ tải về được).
    file_office_preview: bool = True

    # OCR.space đọc chữ trên ảnh danh thiếp khi thêm người liên hệ (https://ocr.space/ocrapi)
    ocr_space_api_key: str = ""
    ocr_space_url: str = "https://api.ocr.space/parse/image"
    ocr_space_engine: int = 2  # engine 2 tự nhận ngôn ngữ, đọc tốt tiếng Việt có dấu
    ocr_max_kb: int = 1024  # gói miễn phí giới hạn 1 MB / ảnh

    # Thông báo Telegram (tạo bot với @BotFather). Bỏ trống token = tắt tính năng.
    telegram_bot_token: str = ""
    telegram_api_url: str = "https://api.telegram.org"
    telegram_poll_seconds: float = 5  # chu kỳ worker xử lý hàng đợi thông báo
    app_public_url: str = "http://localhost:3000"  # để chèn link mở công việc vào tin nhắn


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
