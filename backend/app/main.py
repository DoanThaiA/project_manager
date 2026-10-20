from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.api.v1.api import api_router
from app.core.config import settings

app = FastAPI(
    title=settings.app_name,
    description="API quản lý dự án phần mềm theo Scrum/Agile: yêu cầu khách hàng, backlog, sprint, log công việc.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# SQLSTATE -> (HTTP status, thông báo)
_PG_ERRORS = {
    "23505": (status.HTTP_409_CONFLICT, "Dữ liệu bị trùng"),
    "23503": (status.HTTP_422_UNPROCESSABLE_CONTENT, "Tham chiếu không hợp lệ"),
    "23514": (status.HTTP_422_UNPROCESSABLE_CONTENT, "Dữ liệu vi phạm ràng buộc"),
    "23502": (status.HTTP_422_UNPROCESSABLE_CONTENT, "Thiếu dữ liệu bắt buộc"),
}


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """Chuyển lỗi ràng buộc của PostgreSQL thành 409/422 thay vì 500."""
    cause = getattr(exc.orig, "__cause__", None)
    sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(cause, "sqlstate", None)
    http_status, message = _PG_ERRORS.get(sqlstate, (status.HTTP_400_BAD_REQUEST, "Lỗi dữ liệu"))
    constraint = getattr(cause, "constraint_name", None)
    return JSONResponse(
        status_code=http_status,
        content={"detail": f"{message} ({constraint})" if constraint else message},
    )


@app.exception_handler(DBAPIError)
async def dbapi_error_handler(request: Request, exc: DBAPIError) -> JSONResponse:
    cause = getattr(exc.orig, "__cause__", None)
    if getattr(cause, "sqlstate", None) == "22P02":  # giá trị sai kiểu
        return JSONResponse(status_code=422, content={"detail": "Giá trị không hợp lệ"})
    return JSONResponse(status_code=500, content={"detail": "Lỗi cơ sở dữ liệu"})


@app.get("/health", tags=["Hệ thống"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api_router, prefix="/api/v1")
