# Triển khai lên server (dùng chung PostgreSQL với ai_carbon_analyst)

Project Manager **không** dùng `DATABASE_URL` của carbon (`postgres@…/carbon_analyst`). Nó chỉ dùng chung
**server** PostgreSQL đó, với database `project_manager` và user `pm_user` riêng (không phải superuser,
không vào được database `carbon_analyst`). Superuser `postgres` chỉ dùng một lần trong `init_db.sh`
qua `docker exec`, không cần mật khẩu và không lưu ở đâu trong Project Manager.

```
                  ┌──────────── mạng docker của carbon ────────────┐
nginx ─► web:3000 ─► api:8000 ─┼─► postgres:5432 ─┬─ carbon_analyst  (carbon)  │
 (443)   (Next.js)   (FastAPI) │                  └─ project_manager (pm_user) │
                               └────────────────────────────────────────────────┘
```

## 1. Kiểm tra trên server

```bash
docker ps --format '{{.Names}}\t{{.Image}}' | grep -i postgres   # tên container PostgreSQL (vd: carbon_analyst_db)
docker network ls | grep -i carbon                                # tên mạng (vd: ai_carbon_analyst_default)
docker exec <container> psql -U postgres -Atc 'show server_version'   # cần >= 15
```

`DATABASE_URL` của carbon có host `postgres` → đó là **tên service** trong compose của carbon; dùng được
làm `PM_DB_HOST` khi API nối vào cùng mạng.

## 2. Đưa code lên server

```bash
git clone <repo> /opt/project_manager      # hoặc rsync thư mục dự án (bỏ node_modules, .venv, .next, .env)
cd /opt/project_manager
```

## 3. Tạo `.env`

```bash
cp .env.example .env
python3 -c "import secrets; print('PM_DB_PASSWORD=' + secrets.token_urlsafe(24)); print('SECRET_KEY=' + secrets.token_urlsafe(48))"
```

Điền vào `.env`:

| Biến | Giá trị trên server |
|---|---|
| `PM_DB_PASSWORD`, `SECRET_KEY` | giá trị vừa sinh (khác với máy dev) |
| `PM_DB_HOST` | `postgres` (tên service) hoặc tên container |
| `PM_DB_NETWORK` | tên mạng ở bước 1 |
| `PG_CONTAINER` | tên container ở bước 1 |
| `PM_BIND_ADDR` | `127.0.0.1` — chỉ nginx truy cập được, không lộ cổng ra Internet |

```bash
chmod 600 .env
```

## 4. Khởi tạo database (một lần)

```bash
./scripts/init_db.sh          # KHÔNG dùng --demo trên production (tài khoản mẫu mật khẩu Demo@123)
```

Script tạo `pm_user` + database `project_manager`, đặt múi giờ `Asia/Ho_Chi_Minh` cho riêng database này,
chạy schema và seed vai trò/quyền. Chạy lại an toàn: nếu đã có schema thì bỏ qua.

Nên chặn `pm_user` khỏi database của carbon (superuser `postgres` của carbon không bị ảnh hưởng —
kiểm tra trước carbon không có user đăng nhập nào khác ngoài `postgres`):

```bash
docker exec <container> psql -U postgres -Atc "select rolname from pg_roles where rolcanlogin"
docker exec <container> psql -U postgres -c "REVOKE CONNECT ON DATABASE carbon_analyst FROM PUBLIC"
```

## 5. Chạy ứng dụng và tạo tài khoản quản trị

```bash
docker compose up -d --build
docker compose exec api python -m app.cli create-admin --username admin --email admin@congty.vn --full-name "Quản trị viên"
curl -s localhost:8000/health        # {"status":"ok"}
```

Đăng nhập bằng tài khoản vừa tạo → **Quản trị › Người dùng** để tạo người dùng, **Khách hàng**, rồi tạo dự án.

## 6. Nginx + HTTPS

Chỉ cần proxy tới `web` — Next.js tự chuyển `/api/*` sang FastAPI trong mạng docker.

```nginx
server {
    server_name pm.congty.vn;
    client_max_body_size 20m;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;   # backend ghi IP thật vào nhật ký
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo certbot --nginx -d pm.congty.vn
```

## 7. Backup riêng database `project_manager`

```bash
# crontab -e  (2h sáng mỗi ngày, giữ 14 bản)
0 2 * * * docker exec <container> pg_dump -U pm_user -Fc project_manager > /backup/pm_$(date +\%F).dump && find /backup -name 'pm_*.dump' -mtime +14 -delete
```

Khôi phục: `docker exec -i <container> pg_restore -U pm_user -d project_manager --clean < /backup/pm_YYYY-MM-DD.dump`

## Cập nhật phiên bản

```bash
git pull
docker compose up -d --build
```

Khi có migration mới (`db/migrations/V2__…sql`), chạy trước khi build:
`docker exec -i <container> psql -v ON_ERROR_STOP=1 -U pm_user -d project_manager < db/migrations/V2__….sql`

## Lưu ý

- **Phụ thuộc carbon:** stack carbon dừng thì Project Manager mất database. Không chạy `docker compose down -v`
  trong thư mục carbon — lệnh đó xoá volume chứa **cả hai** database.
- Không đặt mật khẩu superuser `postgres` vào cấu hình Project Manager.
- `BACKEND_URL` của frontend được build cố định là `http://api:8000` (trong mạng docker) — không cần đổi theo domain.
