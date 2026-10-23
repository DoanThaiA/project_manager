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
| `PM_WEB_PORT`, `PM_API_PORT` | cổng còn trống, vd `3100`, `8100` — carbon thường đã dùng 3000/8000 (`ss -ltnp \| grep -E ':(3000\|8000)'`) |

```bash
chmod 600 .env
```

## 4. Khởi tạo database (một lần)

```bash
./scripts/init_db.sh          # KHÔNG dùng --demo trên production (tài khoản mẫu mật khẩu Demo@123)
```

Script tạo `pm_user` + database `project_manager`, đặt múi giờ `Asia/Ho_Chi_Minh` cho riêng database này,
rồi chạy migration Alembic (`alembic upgrade head`: schema + seed vai trò/quyền) trong container API.
Chạy lại an toàn: migration đã áp thì bỏ qua.

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

## 8. Lưu ảnh trên Cloudflare Images

Ảnh đính kèm công việc (ảnh chụp lỗi / ảnh kết quả sau khi sửa) được API tải lên Cloudflare Images;
database chỉ lưu image id (bảng `attachments`). Chưa cấu hình thì tính năng tải ảnh trả lỗi 503,
phần còn lại vẫn chạy bình thường. Cloudflare Images cần gói trả phí (Images Paid).

1. Cloudflare Dashboard › **Images** › **Overview**: bật Images, ghi lại **Account ID** và **Account hash**.
2. **My Profile › API Tokens › Create Token › Custom token**: quyền *Account › Cloudflare Images › Edit*.
3. Chọn chế độ hiển thị:
   - **Riêng tư (khuyên dùng — ảnh lỗi hay chứa dữ liệu khách hàng):** **Images › Keys** › copy key →
     đặt `CF_IMAGES_SIGNING_KEY`. Ảnh tải lên với `requireSignedURLs`, API trả link ký tạm hết hạn sau 1 giờ.
   - **Public:** để trống `CF_IMAGES_SIGNING_KEY` — ai có link `imagedelivery.net/...` đều xem được.
   Đổi chế độ chỉ áp dụng cho ảnh tải lên **sau** khi đổi.
4. Điền vào `.env` rồi `docker compose up -d --build api`:

| Biến | Giá trị |
|---|---|
| `CF_ACCOUNT_ID`, `CF_IMAGES_ACCOUNT_HASH` | từ bước 1 |
| `CF_IMAGES_TOKEN` | token ở bước 2 |
| `CF_IMAGES_SIGNING_KEY` | key ở bước 3, hoặc để trống |

Giới hạn: ảnh PNG / JPEG / GIF / WebP, tối đa 10 MB mỗi ảnh (`ATTACHMENT_MAX_MB`). Ảnh hiển thị qua
variant `public` (có sẵn mặc định, đổi bằng `CF_IMAGES_VARIANT`).

## 9. OCR danh thiếp (OCR.space)

Khi thêm khách hàng hoặc người liên hệ, có thể chụp / chọn ảnh danh thiếp (hoặc giấy tờ công ty): API gửi
ảnh sang [OCR.space](https://ocr.space/ocrapi) rồi tự điền các ô — khách hàng: tên công ty, MST, email, điện
thoại, địa chỉ, website; người liên hệ: họ tên, chức vụ, email, điện thoại (người dùng kiểm tra lại trước khi lưu). Ảnh không được lưu lại. Lấy API key tại ocr.space, đặt `OCR_SPACE_API_KEY` trong `.env`
rồi `docker compose up -d api`; để trống thì nút quét trả lỗi 503, nhập tay vẫn bình thường.

Gói miễn phí giới hạn ảnh 1 MB (`OCR_MAX_KB`); trình duyệt tự thu nhỏ ảnh trước khi gửi.

## 10. Thông báo Telegram

Khi công việc được đổi trạng thái (kéo thả trên Sprint board, sửa công việc, bắt đầu / kết thúc sprint), bot gửi
tin tới **group của dự án** và **chat riêng** của người liên quan. Bot nhận lệnh bằng long polling — không cần
webhook, không cần mở port; container API chỉ cần gọi ra được `https://api.telegram.org`.

1. Trên Telegram, chat với [@BotFather](https://t.me/BotFather):
   - `/newbot` → đặt tên và username (vd `mcv_pm_bot`) → nhận **token**.
   - `/setjoingroups` → chọn bot → **Enable** (cho phép thêm bot vào group).
   - `/setprivacy` → giữ **Enable** (bot chỉ cần đọc lệnh `/start`, không đọc tin khác trong group).
2. Trong `.env`: `TELEGRAM_BOT_TOKEN=<token>`, `APP_PUBLIC_URL=https://dev.mcv.network`, rồi
   `docker compose up -d --build api` (API tự chạy migration 0005).
3. Liên kết chat (token không bao giờ lộ ra trình duyệt; mã liên kết dùng một lần, hết hạn sau 15 phút):
   - **Cá nhân**: menu tài khoản › *Thông báo Telegram* › *Kết nối Telegram* → Telegram mở chat với bot → bấm
     **Start**. Mặc định nhận thông báo khi việc *giao cho mình* hoặc *do mình tạo* đổi trạng thái (không báo
     thay đổi do chính mình làm).
   - **Group**: dự án › *Thông báo* › *Thêm group Telegram* → chọn group → bot vào group và tự liên kết. Cần
     quyền `project.notification.manage` (mặc định: Product Owner, Scrum Master). Có thể lọc chỉ báo khi chuyển
     sang một số trạng thái (vd chỉ *Review*, *Xong*).

Nhiều công việc đổi trạng thái trong cùng một thao tác (vd kết thúc sprint) được gộp thành một tin. Telegram lỗi
thì tin được gửi lại (30 giây → 1 giờ, tối đa 5 lần); bot bị xoá khỏi group / bị chặn thì chat đó ngừng nhận
cho tới khi liên kết lại hoặc bấm *Gửi thử* thành công. Xem lỗi: `docker compose logs -f api | grep -i telegram`.

## Cập nhật phiên bản

```bash
git pull
docker compose up -d --build
```

Migration mới (Alembic, `backend/migrations/versions/`) tự chạy khi container API khởi động
(`alembic upgrade head`); migration lỗi thì API không lên, xem `docker compose logs api`.
Nên backup database (mục 7) trước khi cập nhật bản có migration. Xem / chạy tay:

```bash
docker compose exec api alembic current      # phiên bản đang dùng
docker compose run --rm api alembic upgrade head
```

Database tạo trước khi chuyển sang Alembic không cần làm gì thêm: revision `0001` thấy đã có schema thì
chỉ ghi nhận phiên bản, `0002` dùng `IF NOT EXISTS`.

## Xử lý sự cố

| Triệu chứng | Nguyên nhân / cách xử lý |
|---|---|
| `network ai_carbon_analyst_default declared as external, but could not be found` | Sai `PM_DB_NETWORK` — lấy đúng tên từ `docker network ls` |
| `Thiếu PM_DB_PASSWORD trong .env` | Chạy `docker compose` ngoài thư mục dự án, hoặc `.env` thiếu biến |
| `Bind for 127.0.0.1:3000 failed: port is already allocated` | Đổi `PM_WEB_PORT` / `PM_API_PORT` |
| API log: `password authentication failed for user "pm_user"` | `PM_DB_PASSWORD` khác mật khẩu lúc chạy `init_db.sh` → đặt lại: `docker exec <container> psql -U postgres -c "ALTER ROLE pm_user PASSWORD '<PM_DB_PASSWORD>'"` |
| API log: `could not translate host name "postgres"` | Sai `PM_DB_HOST` hoặc API chưa vào đúng mạng — thử tên container |
| API log: `alembic ... Error` rồi container restart liên tục | Migration lỗi — `docker compose logs api`, sửa rồi `docker compose up -d --build api`; cần thì khôi phục backup |
| Nginx 502 | `web` chưa chạy hoặc sai cổng trong `proxy_pass` — `docker compose ps`, `curl 127.0.0.1:$PM_WEB_PORT/login` |

Xem log: `docker compose logs -f --tail=100 api web`

## Lưu ý

- **Phụ thuộc carbon:** stack carbon dừng thì Project Manager mất database. Không chạy `docker compose down -v`
  trong thư mục carbon — lệnh đó xoá volume chứa **cả hai** database.
- Không đặt mật khẩu superuser `postgres` vào cấu hình Project Manager.
- `BACKEND_URL` của frontend được build cố định là `http://api:8000` (trong mạng docker) — không cần đổi theo domain.
