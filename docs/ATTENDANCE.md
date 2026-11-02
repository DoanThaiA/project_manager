# Chấm công theo IP mạng công ty

> Trạng thái: **đã triển khai** (migration `0013`). API `/api/v1/attendance`, trang *Chấm công của tôi*
> (`/attendance`) và *Quản trị › Chấm công* (`/admin/attendance`). Đưa lên server: mục 6.

Nhân viên bấm **Check-in / Check-out** trên web (máy tính hoặc điện thoại). Server tự lấy IP của request
và so với danh sách **IP công cộng của văn phòng**. Khớp thì ghi giờ, không khớp thì từ chối:

```
Máy nhân viên ─► router văn phòng (IP công cộng 113.161.x.x) ─► Internet ─► nginx ─► web (Next.js) ─► api
                                                                                            │
                                     IP 113.161.x.x thuộc attendance_networks? ◄────────────┘
                                       ├─ có    → ghi attendance_records (giờ = now() của DB)
                                       └─ không → 403, ghi attendance_events (rejected)
```

| Nhân viên đang dùng | Kết quả |
|---|---|
| Wi-Fi / mạng dây công ty | ✅ chấm được |
| Wi-Fi nhà, quán cà phê, 4G/5G (kể cả khi đang ngồi ở công ty) | ❌ bị từ chối |

Phạm vi:

- **Một ca cố định 08:00 – 17:30** cho tất cả mọi người. Mỗi ngày chỉ chấm **2 lần: lúc đến (check-in) và lúc
  về (check-out)**.
- Chấm công **theo từng user**: bản ghi gắn với `users.id`. Ai có quyền `attendance.checkin` thì chấm được.
  **Không dùng bảng `companies`** (LMS), không tách cấu hình hay báo cáo theo công ty.

Nguyên tắc:

- Server chỉ thấy **IP công cộng (WAN)** của văn phòng, không thấy IP LAN `192.168.x.x` của từng máy.
  Cả văn phòng dùng chung một IP (hoặc một dải nhỏ), nên danh sách chỉ cần vài dòng.
- **IP luôn do server tự lấy**, không có trường nào để client gửi IP lên. Giờ chấm lấy theo `now()` của
  database, không lấy giờ của máy nhân viên.
- Chỉ chấp nhận phiên đăng nhập (JWT). **Không cho chấm bằng token PAT** (n8n, MCP, script), để không ai đặt
  được script trên một máy trong văn phòng chấm hộ hằng ngày.
- Cần **IP tĩnh** từ nhà mạng. Nếu IP động, mỗi lần IP đổi admin phải cập nhật lại (mục 4.2).

## 1. Lấy IP thật của client (làm trước tiên)

Trước bản này, `client_ip()` ([deps.py](../backend/app/api/deps.py)) lấy **phần tử đầu** của `X-Forwarded-For`.
Client tự đặt được header này, nên chỉ cần `curl -H "X-Forwarded-For: <IP văn phòng>"` là giả được IP. Bản này
đọc chuỗi proxy từ phải sang trái (mục 1.2), nên IP trong nhật ký audit cũng đúng hơn.

### 1.1 Nginx ghi đè header (khuyên dùng)

Mục 1.2 đã chặn IP giả kể cả khi nginx vẫn dùng `$proxy_add_x_forwarded_for` (nối thêm). Ghi đè bằng
`$remote_addr` thì header gửi tới API gọn hơn và không phụ thuộc vào thứ tự các hop:

```nginx
location / {
    proxy_pass http://127.0.0.1:3000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;   # GHI ĐÈ: bỏ mọi giá trị client tự gửi
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Nếu domain đi qua **Cloudflare proxy** (đám mây cam), `$remote_addr` là IP của Cloudflare. Khi đó bật
module `real_ip` để nginx lấy IP thật trước khi ghi đè:

```nginx
# /etc/nginx/conf.d/cloudflare_real_ip.conf — danh sách dải IP lấy tại https://www.cloudflare.com/ips/
set_real_ip_from 173.245.48.0/20;
set_real_ip_from 103.21.244.0/22;
# ... toàn bộ dải IPv4 + IPv6 của Cloudflare
real_ip_header CF-Connecting-IP;
```

### 1.2 API đọc chuỗi proxy từ phải sang trái

Chuỗi request: nginx → Next.js rewrite → FastAPI. Next.js có thể nối thêm hop của nó vào `X-Forwarded-For`.
Thuật toán của `client_ip()`:

1. `chain = [các IP trong X-Forwarded-For] + [request.client.host]`
2. Duyệt **từ phải sang trái**, bỏ qua các IP thuộc `TRUSTED_PROXIES`.
3. IP đầu tiên **không** thuộc danh sách tin cậy là IP client. Nếu tất cả đều tin cậy (gọi nội bộ) thì
   lấy phần tử trái nhất.
4. Giá trị không phải IP hợp lệ: dừng lại và lấy IP đứng ngay bên phải nó.

```python
# config.py
trusted_proxies: list[str] = ["127.0.0.0/8", "::1/128", "172.16.0.0/12", "10.0.0.0/8"]  # loopback + mạng docker
```

Cách này an toàn cả khi cổng API vô tình mở ra Internet: lúc đó `request.client.host` là IP của kẻ gửi
(không tin cậy) nên được lấy luôn, header giả bị bỏ qua. Dù vậy, trên server vẫn phải đặt
`PM_BIND_ADDR=127.0.0.1` (DEPLOY.md mục 3). Có proxy khác đứng trước nginx (load balancer nội bộ...) thì thêm
dải IP của nó vào `TRUSTED_PROXIES` trong `.env` (dạng JSON, vd `["127.0.0.0/8","172.16.0.0/12"]`).

### 1.3 Endpoint kiểm tra

`GET /attendance/my-ip` trả về IP mà server thấy và mạng công ty khớp với IP đó. Người có quyền
`attendance.manage` thấy thêm `x_forwarded_for` gốc và `client_host` để dò lỗi cấu hình proxy.

## 2. Database (migration `0013_attendance`)

Viết bằng SQL như `0008` / `0012` (`run_sql`), có trigger `fn_set_updated_at` và `fn_audit_log`.

### 2.1 `attendance_networks`: mạng văn phòng được phép chấm

```sql
CREATE TABLE attendance_networks (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        varchar(100) NOT NULL,                 -- "VP Hà Nội - Viettel"
    cidr        cidr         NOT NULL UNIQUE,          -- 113.161.10.20/32, 2402:800:1234::/56
    is_active   boolean      NOT NULL DEFAULT true,
    note        text,
    created_by  bigint REFERENCES users(id) ON DELETE SET NULL,
    created_at  timestamptz  NOT NULL DEFAULT now(),
    updated_at  timestamptz  NOT NULL DEFAULT now()
);
-- Tra cứu: SELECT id, name FROM attendance_networks WHERE is_active AND cidr >>= :ip::inet LIMIT 1
```

Ràng buộc khi thêm/sửa (kiểm tra ở API, trả 422 kèm thông báo):

- Không nhận dải quá rộng: IPv4 tối thiểu `/24`, IPv6 tối thiểu `/48`. Chặn `0.0.0.0/0`, `::/0`.
- Không nhận IP nội bộ (`10/8`, `172.16/12`, `192.168/16`, `127/8`, `fc00::/7`, `fe80::/10`), vì server
  không bao giờ thấy các IP này từ client thật. Máy dev đặt `ATTENDANCE_ALLOW_PRIVATE_NETWORKS=true`
  (`backend/.env`) để khai báo được `127.0.0.1` và test bằng localhost. Production luôn để `false` (mặc định).

### 2.2 Ca làm: cấu hình cố định, không có bảng

Chỉ có **một ca cố định**, nên ca làm đặt trong `config.py` (đổi qua `.env` nếu cần) chứ không lưu thành
bảng, và không có màn hình sửa ca:

```python
# config.py
attendance_start_time: time = time(8, 0)       # giờ vào
attendance_end_time: time = time(17, 30)       # giờ về
attendance_break_start: time = time(12, 0)     # nghỉ trưa, không tính vào giờ làm
attendance_break_end: time = time(13, 30)
attendance_late_grace_minutes: int = 5         # vào muộn <= 5 phút không tính là đi muộn
attendance_early_grace_minutes: int = 0
attendance_work_days: list[int] = [1, 2, 3, 4, 5]  # ISO: 1 = thứ 2 ... 7 = chủ nhật
```

`late_minutes` / `early_leave_minutes` được tính và lưu ngay lúc chấm theo giờ vào / về ở trên.

### 2.3 `attendance_records`: bảng công, mỗi người một dòng mỗi ngày

```sql
CREATE TABLE attendance_records (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id              bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    work_date            date   NOT NULL,                 -- ngày theo giờ Việt Nam
    check_in_at          timestamptz NOT NULL,
    check_in_ip          inet,
    check_in_network_id  bigint REFERENCES attendance_networks(id) ON DELETE SET NULL,
    check_out_at         timestamptz,
    check_out_ip         inet,
    check_out_network_id bigint REFERENCES attendance_networks(id) ON DELETE SET NULL,
    late_minutes         int NOT NULL DEFAULT 0,          -- số phút vào sau 08:00
    early_leave_minutes  int NOT NULL DEFAULT 0,          -- số phút về trước 17:30
    worked_minutes       int,                             -- (ra - vào) - phần trùng giờ nghỉ trưa
    source               varchar(10) NOT NULL DEFAULT 'web' CHECK (source IN ('web', 'admin')),
    note                 text,
    adjusted_by          bigint REFERENCES users(id) ON DELETE SET NULL,
    adjusted_reason      text,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_attendance_records_user_date UNIQUE (user_id, work_date),
    CONSTRAINT ck_attendance_records_out_after_in CHECK (check_out_at IS NULL OR check_out_at >= check_in_at),
    CONSTRAINT ck_attendance_records_admin_reason CHECK (source = 'web' OR adjusted_reason IS NOT NULL)
);
CREATE INDEX ix_attendance_records_date ON attendance_records(work_date);
```

- `work_date = (now() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date`. Database đã đặt sẵn múi giờ này. Không có ca
  qua đêm.
- **Không lưu cột trạng thái.** Trạng thái được suy ra khi đọc, nên đổi số phút cho phép không làm dữ liệu cũ sai:

| Trạng thái | Điều kiện |
|---|---|
| Đi muộn | `late_minutes > late_grace_minutes` |
| Về sớm | `early_leave_minutes > early_grace_minutes` |
| Thiếu check-out | `check_out_at IS NULL` và `work_date` < hôm nay |
| Ngoài ngày làm việc | thứ của `work_date` không có trong `work_days` (làm thêm cuối tuần) |
| Vắng | ngày làm việc không có dòng nào (tính trong báo cáo, không tạo dòng) |

### 2.4 `attendance_events`: log thô mọi lần bấm

```sql
CREATE TABLE attendance_events (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    action      varchar(10) NOT NULL CHECK (action IN ('check_in', 'check_out')),
    accepted    boolean     NOT NULL,
    reason      varchar(30),          -- outside_network | not_checked_in | api_token
    ip          inet,
    network_id  bigint REFERENCES attendance_networks(id) ON DELETE SET NULL,
    user_agent  text,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_attendance_events_user ON attendance_events(user_id, created_at DESC);
CREATE INDEX ix_attendance_events_rejected ON attendance_events(created_at DESC) WHERE NOT accepted;
```

Bảng này dùng để tra gian lận (ví dụ một người bị từ chối nhiều lần từ cùng một IP lạ) và để giải đáp khi
nhân viên báo "em bấm rồi mà không được". Không gắn audit trigger. Log IP và user agent là dữ liệu cá nhân:
giữ 12 tháng rồi xoá, ví dụ cron hằng tháng:

```bash
0 3 1 * * docker exec <container> psql -U pm_user -d project_manager -c "DELETE FROM attendance_events WHERE created_at < now() - interval '12 months'"
```

### 2.5 Quyền

Quyền cấp **hệ thống** (gán qua `user_roles`, không gắn với dự án):

```sql
INSERT INTO permissions (code, module, name) VALUES
    ('attendance.checkin', 'attendance', 'Chấm công (check-in / check-out)'),
    ('attendance.view',    'attendance', 'Xem bảng công của mọi người'),
    ('attendance.manage',  'attendance', 'Cấu hình mạng công ty, sửa công');
INSERT INTO roles (code, name, scope, is_builtin, description) VALUES
    ('HR', 'Nhân sự', 'system', true, 'Quản lý chấm công');
```

| Vai trò | checkin | view | manage |
|---|:-:|:-:|:-:|
| SYSTEM_ADMIN | ✅ | ✅ | ✅ |
| HR (mới, kèm `user.view`) | ✅ | ✅ | ✅ |
| PROJECT_MANAGER, STAFF | ✅ | | |
| EXECUTIVE | | ✅ | |
| CUSTOMER và các vai trò dự án | | | |

Tài khoản khách hàng (`CUSTOMER`) và tài khoản bot (`bot.n8n`) không có `attendance.checkin`. Admin chỉnh
thêm được ở **Vai trò & quyền**.

## 3. API `/api/v1/attendance`

File mới `endpoints/attendance.py`, `schemas/attendance.py`, `models/attendance.py`,
`services/attendance.py` (phần tính toán: so IP, tính phút muộn / về sớm / giờ làm). Đăng ký router với
tag `"Chấm công"`.

### 3.1 Nhân viên (`attendance.checkin`)

| Endpoint | Mô tả |
|---|---|
| `GET /me/today` | Trạng thái hôm nay: IP, có ở mạng công ty không, giờ vào / về quy định, bản ghi hôm nay, nút nào bấm được |
| `POST /check-in` | Body `{ "note"?: str }`. Ngoài mạng công ty → **403**. Đã check-in → trả bản ghi cũ (200, không ghi đè giờ vào) |
| `POST /check-out` | Chưa check-in → **409**. Check-out nhiều lần thì **giữ lần cuối** (về rồi quay lại làm tiếp) |
| `GET /me/records?month=2026-11` | Lịch công tháng của tôi, kèm trạng thái suy ra và các ngày vắng |
| `GET /my-ip` | IP server thấy + mạng khớp (mục 1.3) |

`GET /me/today`, ví dụ:

```json
{
  "work_date": "2026-11-02",
  "ip": "113.161.10.20",
  "network": { "id": 1, "name": "VP Hà Nội - Viettel" },
  "shift": { "start_time": "08:00", "end_time": "17:30", "is_work_day": true },
  "record": { "check_in_at": "2026-11-02T08:11:03+07:00", "check_out_at": null, "late_minutes": 11, "is_late": true },
  "can_check_in": false,
  "can_check_out": true
}
```

Từ chối vì ngoài mạng:

```json
{ "detail": "Bạn đang không dùng mạng công ty (IP 14.231.5.6). Hãy kết nối Wi-Fi văn phòng rồi thử lại." }
```

Thứ tự kiểm tra ở `check-in` / `check-out`:

1. Đăng nhập bằng PAT → 403 `api_token`.
2. Không có quyền `attendance.checkin` → 403 (không ghi event).
3. IP không khớp mạng nào đang bật → 403 `outside_network`.
4. Tính toán và ghi bản ghi. Mọi lần bấm, kể cả bị từ chối ở bước 1 và 3, đều ghi một dòng `attendance_events`.

Chống bấm đúp: `INSERT ... ON CONFLICT (user_id, work_date) DO NOTHING RETURNING ...`, nên hai request cùng lúc
không tạo hai bản ghi.

### 3.2 Quản lý

| Endpoint | Quyền | Mô tả |
|---|---|---|
| `GET /networks`, `POST /networks`, `PATCH/DELETE /networks/{id}` | manage | Mạng văn phòng |
| `POST /networks/current-ip` | manage | Body `{ "name": str }`: thêm IP đang dùng. IPv4 → `/32`, IPv6 → `/64` |
| `GET /records?from&to&user_id&status` | view | Bảng công, phân trang như các API khác |
| `POST /records` | manage | Thêm công cho ngày nhân viên quên chấm. Bắt buộc `adjusted_reason`, `source='admin'` |
| `PATCH /records/{id}` | manage | Sửa giờ vào / ra. Bắt buộc `adjusted_reason`, tính lại số phút. Thay đổi ghi vào nhật ký hệ thống |
| `DELETE /records/{id}` | manage | Xoá bản ghi sai |
| `GET /summary?month=` | view | Theo từng người: số ngày có mặt, số lần / tổng phút đi muộn, về sớm, thiếu check-out, vắng, tổng giờ làm |
| `GET /summary/export?month=` | view | CSV UTF-8 có BOM (mở thẳng bằng Excel) |
| `GET /events?user_id&accepted` | manage | Log thô, xem các lần bị từ chối |

## 4. Giao diện

### 4.1 Nhân viên

- **Trang Tổng quan (`/`)**: thẻ *Chấm công* ở đầu trang:
  - Nút **Check-in** / **Check-out** to, dễ bấm trên điện thoại.
  - Giờ vào / ra hôm nay, nhãn *Đi muộn 11 phút* nếu có.
  - Dòng nhỏ: *Mạng: VP Hà Nội · IP 113.161.10.20*. Ngoài mạng thì hiện cảnh báo vàng và khoá nút.
- **`/attendance`** (menu *Chấm công của tôi*): lịch tháng, mỗi ngày tô màu theo trạng thái (đúng giờ / muộn /
  về sớm / thiếu check-out / vắng); tổng số ngày công và số lần đi muộn trong tháng.

### 4.2 Quản lý (`/admin/attendance`, menu *Chấm công*, `perm: "attendance.view"`)

| Tab | Nội dung |
|---|---|
| Bảng công | Lọc theo tháng / người / trạng thái; sửa giờ, thêm công (bắt buộc nhập lý do); xuất CSV |
| Tổng hợp tháng | Bảng theo người, số liệu như `GET /summary` |
| Mạng công ty | Danh sách CIDR, bật / tắt; nút **Thêm IP tôi đang dùng** (bấm khi đang ở văn phòng) |
| Lần bị từ chối | Log `attendance_events` có `accepted = false` |

Tab nào cũng chỉ hiện với người có quyền tương ứng (`attendance.manage` cho 2 tab cuối). Backend vẫn kiểm tra
lại quyền. Sau khi xong backend, chạy `npm run gen:api`.

## 5. Test (`backend/tests/test_attendance.py`)

- IP trong / ngoài CIDR, IPv4 và IPv6. Mạng bị tắt thì không khớp.
- **`X-Forwarded-For` giả bị bỏ qua**: header `"<IP VP>, <IP thật>"` thì lấy IP thật. Có hop docker tin cậy ở
  bên phải thì vẫn lấy đúng IP client.
- Check-in hai lần → giữ giờ đầu. Check-out hai lần → giữ giờ cuối. Check-out khi chưa check-in → 409.
- Đăng nhập bằng PAT → 403 và có ghi event.
- Tính `late_minutes`, `early_leave_minutes`, `worked_minutes` (có / không trùng giờ nghỉ trưa); đúng giờ biên
  `late_grace_minutes`.
- `work_date` đúng giờ Việt Nam: 23:59 và 00:01 là hai ngày khác nhau.
- Validate CIDR: chặn `/0`, dải quá rộng, IP nội bộ khi chạy ở production.
- Phân quyền: CUSTOMER không chấm được; STAFF không xem được bảng công người khác; sửa công thiếu lý do → 422.
- `summary`: ngày vắng, thiếu check-out, ngày cuối tuần không tính là vắng.

## 6. Triển khai lên server

1. **Chuẩn bị**: xác nhận văn phòng có IP tĩnh. Đứng ở văn phòng mở trang "what is my IP" để biết IPv4 (và IPv6
   nếu có). Có nhiều đường mạng (2 nhà mạng, chi nhánh) thì ghi lại từng đường.
2. **Backup database** (DEPLOY.md mục 7), rồi cập nhật:

   ```bash
   cd /opt/project_manager && git pull && docker compose up -d --build
   docker compose exec api alembic current      # phải thấy 0013 (head)
   ```

3. **Sửa nginx** theo mục 1.1 (thêm `real_ip` nếu dùng Cloudflare), rồi `sudo nginx -t && sudo systemctl reload nginx`.
4. **Kiểm tra không giả được IP**, chạy từ một máy **ngoài** văn phòng:

   ```bash
   curl -s -H "Authorization: Bearer <JWT>" -H "X-Forwarded-For: <IP văn phòng>" https://<domain>/api/v1/attendance/my-ip
   ```

   Kết quả phải là IP thật của máy đang chạy lệnh, **không phải** IP văn phòng.
5. **Khai báo mạng**: admin đứng ở văn phòng → **Quản trị › Chấm công › Mạng công ty** → *Thêm IP tôi đang
   dùng*. Lặp lại cho từng đường mạng khác.
6. **Kiểm tra thực tế**: chấm thử bằng Wi-Fi công ty (phải được); tắt Wi-Fi, dùng 4G (phải bị từ chối).
7. Gán vai trò **Nhân sự** cho người phụ trách, kiểm tra vai trò STAFF đã có
   `attendance.checkin`, rồi thông báo cho nhân viên.

### Xử lý sự cố

| Triệu chứng | Nguyên nhân / cách xử lý |
|---|---|
| Ở công ty mà cả văn phòng bị từ chối | IP đổi (IP động, đổi nhà mạng, modem dự phòng). Xem `my-ip` rồi cập nhật mạng |
| Một vài người bị từ chối | Họ đang dùng 4G hoặc Wi-Fi khác, hoặc máy dùng IPv6 mà chưa khai prefix IPv6 |
| `my-ip` ra `127.0.0.1` / `172.x.x.x` | Nginx chưa gửi `X-Forwarded-For`, hoặc `TRUSTED_PROXIES` thiếu hop |
| `my-ip` ra IP của Cloudflare | Chưa cấu hình `real_ip` (mục 1.1) |
| Ở nhà vẫn chấm được | Đang bật VPN full-tunnel về văn phòng: tách dải IP VPN, hoặc cấu hình VPN không đi qua IP đó |

## 7. Giới hạn và phần làm sau

Kiểm tra IP chứng minh **thiết bị đang dùng mạng công ty**, không chứng minh **người** đang ở đó:

- **Không chặn được bấm hộ** (đưa tài khoản cho đồng nghiệp ở công ty bấm). Giai đoạn sau: gắn thiết bị (mỗi
  thiết bị chỉ chấm cho một người mỗi ngày) và kiosk **QR động** đổi mã mỗi 30 giây ở cửa văn phòng.
- **Wi-Fi khách dùng chung IP công cộng** với mạng nội bộ thì khách cũng "ở mạng công ty". Muốn tách thì mạng
  khách phải ra Internet bằng đường / IP khác.
- Trình duyệt không đọc được tên Wi-Fi (SSID) hay địa chỉ MAC, nên muốn kiểm tra theo Wi-Fi thì phải làm app riêng.

Ngoài phạm vi MVP, làm ở giai đoạn 2:

- Đơn giải trình (quên chấm, đi công tác, làm ngoài văn phòng) và luồng duyệt.
- Ngày lễ, nghỉ phép; quy đổi ngày công (0.5 / 1 công) theo quy chế nhân sự.
- Telegram nhắc khi chưa check-in sau giờ vào (dùng worker thông báo có sẵn).
- Tool MCP `attendance_summary` cho ban lãnh đạo; so giờ công với giờ log công việc.
- Nhận log từ máy chấm công khuôn mặt nếu công ty mua sau này.

## 8. Danh sách file thay đổi

| File | Việc |
|---|---|
| `backend/app/api/deps.py`, `backend/app/core/config.py` | `client_ip()` mới + `trusted_proxies`, giờ vào / về cố định `attendance_*` |
| `backend/migrations/versions/0013_attendance.py` | 3 bảng (`attendance_networks`, `attendance_records`, `attendance_events`), quyền, vai trò HR |
| `backend/app/models/attendance.py`, `backend/app/models/__init__.py` | Model |
| `backend/app/schemas/attendance.py`, `backend/app/services/attendance.py` | Schema, phần tính toán |
| `backend/app/api/v1/endpoints/attendance.py`, `backend/app/api/v1/api.py` | Router `/attendance` |
| `backend/tests/test_attendance.py` | Test mục 5 |
| `frontend/src/app/(app)/page.tsx` | Thẻ chấm công |
| `frontend/src/app/(app)/attendance/page.tsx`, `frontend/src/app/(app)/admin/attendance/page.tsx` | Trang mới |
| `frontend/src/components/app-shell.tsx`, `frontend/src/lib/api-schema.d.ts` | Menu, kiểu API |
| `docs/DEPLOY.md` (mục 6), `README.md` | Cấu hình nginx, bảng trang / API |
