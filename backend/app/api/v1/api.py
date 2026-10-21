from fastapi import APIRouter

from app.api.v1.endpoints import (
    attachments,
    auth,
    customers,
    projects,
    reports,
    requirements,
    roles,
    sprints,
    users,
    work_items,
    work_logs,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["Xác thực"])
api_router.include_router(work_logs.me_router, prefix="/me", tags=["Cá nhân"])
api_router.include_router(users.router, prefix="/users", tags=["Người dùng"])
api_router.include_router(roles.router, tags=["Vai trò & chức năng"])
api_router.include_router(customers.router, prefix="/customers", tags=["Khách hàng"])
api_router.include_router(projects.router, prefix="/projects", tags=["Dự án"])
api_router.include_router(sprints.router, prefix="/projects/{project_id}/sprints", tags=["Sprint"])
api_router.include_router(
    requirements.router, prefix="/projects/{project_id}/requirements", tags=["Yêu cầu khách hàng"]
)
api_router.include_router(work_items.router, prefix="/projects/{project_id}/work-items", tags=["Backlog / Công việc"])
api_router.include_router(attachments.router, prefix="/projects/{project_id}/work-items", tags=["Backlog / Công việc"])
api_router.include_router(work_logs.router, prefix="/projects/{project_id}/work-logs", tags=["Log công việc"])
api_router.include_router(reports.router, prefix="/projects/{project_id}", tags=["Báo cáo & Nhật ký"])
api_router.include_router(reports.system_router, prefix="/activity-logs", tags=["Báo cáo & Nhật ký"])
