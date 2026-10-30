# MCP server cho ban lãnh đạo (connector URL)

Ban lãnh đạo kết nối vào hệ thống bằng **một URL HTTPS**, dán vào Claude (Desktop hoặc web) hoặc Codex. Không cần đăng nhập OAuth.

```
https://dev.mcv.network/mcp/<token>
```

`<token>` là personal access token của tài khoản ban lãnh đạo. Ai có URL là đọc được dữ liệu theo quyền của tài khoản đó,
nên URL phải được coi như mật khẩu.

## 1. Thành phần

| Thành phần | Vai trò |
|---|---|
| `api` (FastAPI) | Kiểm tra token, phân quyền, ghi nhật ký. Có thêm `/me/api-tokens` và vai trò `EXECUTIVE` (migration `0011`) |
| `mcp` (`app/mcp_server/`) | Nhận request MCP tại `/mcp/<token>`, gọi REST nội bộ của `api` bằng chính token đó |
| nginx (trên host) | TLS, chuyển `/mcp/` tới `127.0.0.1:${PM_MCP_PORT}`, giới hạn tần suất, tắt access log cho `/mcp/` |

Vai trò `EXECUTIVE` chỉ đọc: xem toàn bộ dự án (kể cả không phải thành viên), tiến độ sprint, yêu cầu và bình luận nội bộ,
công việc, giờ log, báo cáo, nhật ký hoạt động, thành viên, khách hàng. Không tạo, sửa hay xoá được gì.

## 2. Tools

| Tool | Trả lời |
|---|---|
| `list_projects` | Danh sách dự án, lọc theo trạng thái, tìm theo tên/mã |
| `project_overview` | Yêu cầu theo trạng thái (và quá hạn), công việc, tổng giờ log, ngân sách, sprint đang chạy |
| `list_sprints` | Sprint của dự án |
| `sprint_progress` | Tiến độ sprint: story point kế hoạch/hoàn thành, giờ log (mặc định sprint đang chạy) |
| `list_requirements` | Yêu cầu khách hàng; lọc quá hạn, trạng thái, mức ưu tiên |
| `requirement_detail` | Chi tiết yêu cầu, lịch sử trạng thái, 30 bình luận gần nhất |
| `list_work_items` | Công việc; lọc sprint, người phụ trách, backlog |
| `team_performance` | Giờ log theo người / sprint / loại việc / ngày, trong khoảng ngày |
| `project_members` | Thành viên và vai trò trong dự án |
| `activity_timeline` | Nhật ký thay đổi: ai đổi gì, lúc nào |
| `list_customers` | Khách hàng |

Tool trả về tối đa 50 bản ghi mỗi lần (`limit`); kết quả có `total` để biết còn dữ liệu hay không.

## 3. Triển khai trên VPS

### 3.1. Cập nhật mã và cấu hình

```bash
cd /opt/project_manager
git pull
```

Thêm vào `.env` (xem `.env.example`):

```bash
PM_MCP_PORT=8100                              # cổng nội bộ, chỉ 127.0.0.1
MCP_PUBLIC_BASE_URL=https://dev.mcv.network       # domain HTTPS đang dùng cho nginx
```

```bash
docker compose up -d --build                   # api tự chạy migration 0011 khi khởi động
docker compose ps                              # thấy project_manager_mcp đang chạy
curl -s 127.0.0.1:8100/healthz                 # ok
```

### 3.2. nginx

Thêm vào khối `http {}` (một lần, ví dụ trong `/etc/nginx/nginx.conf` hoặc file conf.d):

```nginx
limit_req_zone $binary_remote_addr zone=pm_mcp:10m rate=60r/m;
```

Trong `server {}` của `dev.mcv.network`, thêm trước `location /`:

```nginx
    # Connector MCP: URL chứa token, không ghi access log
    location /mcp/ {
        access_log off;
        limit_req zone=pm_mcp burst=30 nodelay;
        proxy_pass http://127.0.0.1:8100;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;         # trả kết quả liên tục
        proxy_read_timeout 120s;
    }
```

```bash
sudo nginx -t && sudo systemctl reload nginx
curl -s -o /dev/null -w "%{http_code}\n" https://dev.mcv.network/mcp/thu-sai   # 404
```

Lưu ý:
- `access_log off` chỉ tắt log truy cập. Nếu nginx ghi **lỗi** (vd: upstream không chạy), dòng lỗi có thể chứa đường dẫn đầy đủ.
  Nếu nghi ngờ URL đã lọt vào log, cấp lại URL (mục 4) và kiểm tra `error.log`.
- Connector gọi từ cloud của Anthropic, nên mọi người dùng connector có thể dùng chung một IP nguồn. Nếu `limit_req` chặn nhầm,
  tăng `rate` hoặc `burst`.

### 3.3. Tạo tài khoản và cấp URL

```bash
docker compose exec api python -m app.cli create-executive \
    --username <ten-dang-nhap> --email <email> --full-name "<Họ tên>"

docker compose exec api python -m app.cli issue-mcp-url --username <ten-dang-nhap> --days 180
# In ra: https://dev.mcv.network/mcp/pm_pat_...   (chỉ in một lần, gửi cho người dùng qua kênh riêng tư)
```

Có thể kiểm tra trước khi giao cho người dùng:

```bash
curl -s -X POST "https://dev.mcv.network/mcp/<token>" \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"kiemtra","version":"0"}}}'
```

## 4. Kết nối từ client

**Claude (Desktop hoặc web):** Settings → Connectors → Add custom connector → dán URL → Add. Không nhập client ID hay secret.

**Codex:** thêm vào `~/.codex/config.toml` một server dạng URL (kiểm tra tên khoá theo phiên bản Codex đang dùng):

```toml
[mcp_servers.project-manager]
url = "https://dev.mcv.network/mcp/<token>"
```

## 5. Xoay và thu hồi

```bash
# Cấp URL mới: URL cũ bị thu hồi ngay
docker compose exec api python -m app.cli issue-mcp-url --username <ten-dang-nhap> --days 180

# Thu hồi hẳn (không cấp lại)
docker compose exec api python -m app.cli revoke-mcp-url --username <ten-dang-nhap>
```

Token có hạn tối đa 365 ngày. Khi hết hạn, URL trả 404 và cần cấp lại.

## 6. Kiểm thử

```bash
cd backend
uv run pytest tests/test_api_tokens.py tests/test_mcp_server.py
```

Các test kiểm tra: token hết hạn, bị thu hồi, không tồn tại; token của người khác không thu hồi được; vai trò `EXECUTIVE` đọc được mọi dự án
nhưng không tạo được dự án; URL sai trả 404; tần suất vượt mức trả 429; tool gửi đúng đường dẫn và giới hạn kết quả.

## 7. Giới hạn hiện tại

- Chỉ đọc. Không có tool ghi.
- Mỗi tài khoản có một URL connector (cấp lại sẽ thay thế URL cũ).
- Dữ liệu trả về được gửi tới cloud của nhà cung cấp model đang dùng connector. Cần được phép trước khi đưa vào sử dụng.
