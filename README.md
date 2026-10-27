# Project Manager

Hệ thống quản lý dự án phần mềm theo Scrum/Agile: yêu cầu khách hàng, backlog, sprint, log công việc, log hoạt động.

```
db/seeds/    Dữ liệu mẫu cho dev
backend/     API FastAPI + SQLAlchemy 2 async; migration Alembic ở backend/migrations
frontend/    Giao diện Next.js 16 + Tailwind 4 + TanStack Query
docs/        Tài liệu thiết kế database
```

## Database: dùng chung PostgreSQL với ai_carbon_analyst

Không chạy PostgreSQL riêng. Dự án dùng **server của `ai_carbon_analyst`** (container `carbon_analyst_db`, PG 16)
nhưng tách biệt hoàn toàn:

- Database riêng `project_manager`, user riêng `pm_user` (không phải superuser, không CONNECT được vào `carbon_analyst`).
- Múi giờ đặt riêng cho database: `Asia/Ho_Chi_Minh` (server chạy UTC).
- Từ máy host: `localhost:5433` (chỉ localhost). API trong Docker nối qua mạng `ai_carbon_analyst_default`.
- Mật khẩu `pm_user` nằm trong `.env` ở thư mục gốc (`PM_DB_PASSWORD`, không commit).

Khởi tạo lần đầu (cần `carbon_analyst_db` đang chạy):

```bash
cp .env.example .env            # điền PM_DB_PASSWORD, SECRET_KEY (giá trị ngẫu nhiên)
./scripts/init_db.sh --demo     # tạo user + database, chạy migration Alembic (+ dữ liệu mẫu)
```

Triển khai lên server: xem [docs/DEPLOY.md](docs/DEPLOY.md). Tạo tài khoản quản trị đầu tiên (production không nạp dữ liệu mẫu):
`docker compose exec api python -m app.cli create-admin --username admin --email … --full-name "…"`

Script không xoá dữ liệu có sẵn; dữ liệu mẫu chỉ nạp khi database còn trống.

## Chạy nhanh bằng Docker

```bash
docker compose up -d --build
```

- Giao diện: http://localhost:3000
- API: http://localhost:8000 · Swagger: http://localhost:8000/docs
- Tài khoản mẫu (mật khẩu `Demo@123`): `admin`, `po.an` (PO), `sm.binh` (Scrum Master), `dev.cuong` (Dev), `qa.dung` (Tester), `kh.abc` (khách hàng)

## Chạy backend khi phát triển

```bash
cd backend
cp .env.example .env    # điền mật khẩu PM_DB_PASSWORD vào DATABASE_URL
uv sync
uv run alembic upgrade head   # áp migration lên database dev
uv run uvicorn app.main:app --reload
uv run pytest          # tự tạo lại DB project_manager_test trên cùng server; có chốt chặn không chạy trên DB dev
uvx ruff check app tests migrations
```

### Migration database (Alembic)

Schema do Alembic quản lý trong `backend/migrations/`. Revision `0001` là schema gốc viết bằng SQL
(`migrations/sql/`: hàm, trigger, view, seed vai trò/quyền). Container API tự chạy `alembic upgrade head`
mỗi lần khởi động.

```bash
cd backend
uv run alembic revision --autogenerate -m "them cot x"   # sinh từ thay đổi model, ĐỌC LẠI trước khi chạy
uv run alembic revision -m "them trigger y"              # viết tay (op.execute(...)) cho trigger/view/dữ liệu
uv run alembic upgrade head                              # áp lên database dev
uv run alembic downgrade -1                              # quay lại 1 bước
uv run alembic current / history                         # xem phiên bản
uv run pytest                                            # test tạo DB mới bằng upgrade head
```

Autogenerate chỉ so sánh bảng / cột / index có khai báo trong model. Nó bỏ qua khoá ngoại, trigger, view
và những gì chỉ có trong SQL, vì vậy các thay đổi này phải tự viết trong migration.

## Chạy frontend khi phát triển

```bash
cd frontend
npm install
npm run dev                # http://localhost:3000, gọi API qua rewrite /api -> BACKEND_URL (mặc định :8000)
npm run gen:api            # sinh lại kiểu TypeScript từ OpenAPI khi backend đổi schema
npx tsc --noEmit && npm run lint
```

Frontend chạy phía client sau đăng nhập (JWT trong localStorage). Ẩn/hiện nút và tab theo quyền
(`/auth/me` cho quyền hệ thống, `/projects/{pid}/my-permissions` cho quyền trong dự án); backend vẫn kiểm tra lại mọi quyền.

| Trang | Chức năng |
|---|---|
| `/` | Tổng quan cá nhân: dự án tham gia, giờ log tuần này |
| `/projects` | Danh sách, tạo dự án |
| `/projects/[pid]` | Tổng quan dự án, sprint đang chạy, thống kê trạng thái |
| `…/requirements` | Yêu cầu khách hàng: lọc, tìm kiếm, sắp xếp, tạo mới |
| `…/requirements/[rid]` | Chi tiết, chuyển trạng thái (duyệt/từ chối có ghi chú), bình luận (nội bộ), lịch sử, nhật ký, tách công việc |
| `…/backlog` | Product Backlog + sprint: kéo thả lập kế hoạch, sắp xếp ưu tiên, tạo/bắt đầu sprint |
| `…/board` | Sprint board Kanban kéo thả, kết thúc sprint (review/retro) |
| `…/work-logs` | Log công việc, tổng hợp theo người/ngày/loại/sprint |
| `…/members`, `…/activity` | Thành viên & vai trò, nhật ký thay đổi |
| `/timesheet` | Bảng giờ theo tuần của tôi |
| `/customers` | Khách hàng & người liên hệ |
| `/admin/users`, `/admin/roles`, `/admin/activity` | Người dùng, ma trận phân quyền, nhật ký hệ thống |

## API (`/api/v1`)

Xác thực bằng JWT Bearer: `POST /auth/login` (form `username`, `password`) rồi gửi kèm header `Authorization: Bearer <token>`.

| Nhóm | Endpoint |
|---|---|
| Xác thực | `POST /auth/login`, `GET /auth/me`, `POST /auth/change-password` |
| Người dùng | `GET/POST /users`, `GET/PATCH/DELETE /users/{id}`, `PUT /users/{id}/roles`, `POST /users/{id}/lock` `/unlock` `/reset-password` |
| Vai trò & chức năng | `GET /permissions`, `GET/POST /roles`, `GET/PATCH/DELETE /roles/{id}`, `PUT /roles/{id}/permissions` |
| Khách hàng | `GET/POST /customers`, `GET/PATCH/DELETE /customers/{id}`, `/customers/{id}/contacts` |
| Dự án | `GET/POST /projects`, `GET/PATCH/DELETE /projects/{pid}`, `GET /projects/{pid}/my-permissions`, `GET/POST/DELETE /projects/{pid}/members` |
| Sprint | `/projects/{pid}/sprints`, `POST …/{sid}/start`, `POST …/{sid}/complete`, `GET …/{sid}/progress` |
| Yêu cầu KH | `/projects/{pid}/requirements`, `POST …/{rid}/status`, `GET …/{rid}/history`, `GET …/{rid}/activity`, `…/{rid}/comments` |
| Backlog | `/projects/{pid}/work-items` (lọc `backlog=true`, `sprint_id`, `status`, `assignee_id` = công việc có người này trong danh sách phụ trách…) |
| Log công việc | `/projects/{pid}/work-logs`, `GET /me/work-logs` |
| Báo cáo & nhật ký | `GET /projects/{pid}/reports/summary`, `GET /projects/{pid}/reports/work-logs?group_by=user\|date\|activity_type\|work_item\|sprint`, `GET /projects/{pid}/activity-logs`, `GET /activity-logs` |

### Quy tắc nghiệp vụ chính

- **Phân quyền 2 cấp**: vai trò hệ thống (`user_roles`) và vai trò trong dự án (`project_members`); kiểm tra bằng hàm DB `fn_user_has_permission`.
- **Luồng trạng thái yêu cầu** được kiểm tra ở API (`TRANSITIONS` trong `requirements.py`); chuyển sang `approved`/`rejected` cần quyền `requirement.approve`, từ chối bắt buộc có lý do.
- Công việc gắn yêu cầu chuyển sang `in_progress` → yêu cầu đang `approved` tự chuyển `in_progress`.
- Bình luận `is_internal` bị ẩn với người không có quyền `requirement.view_internal` (vd: khách hàng).
- Log công việc: không log ngày tương lai, tổng ≤ 24h/ngày/người, tự trừ `remaining_hours` của công việc, tự gắn sprint; chỉ sửa/xoá log của mình trừ khi có `work_log.manage`.
- Kết thúc sprint: việc chưa xong chuyển về backlog hoặc sang sprint kế tiếp.
- **Audit**: mỗi transaction đặt `app.current_user_id` / `app.client_ip` (xem `app/db/session.py`), trigger DB ghi `activity_logs` với giá trị cũ/mới. Đăng nhập, đăng nhập thất bại cũng được ghi.

Tài liệu thiết kế database: [docs/DATABASE.md](docs/DATABASE.md)
# project_manager
