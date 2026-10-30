"""Chạy: python -m app.mcp_server (cổng settings.mcp_port, chỉ nên mở cho nginx trên cùng máy)."""

import uvicorn

from app.core.config import settings
from app.mcp_server.http import build_app


def main() -> None:
    # access_log=False: URL connector chứa token, không được ghi vào log
    uvicorn.run(build_app(), host="0.0.0.0", port=settings.mcp_port, access_log=False)


if __name__ == "__main__":
    main()
