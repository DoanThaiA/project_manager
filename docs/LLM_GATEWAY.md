# AI Gateway: dự án gọi Anthropic / OpenAI qua key riêng, có hạn mức

Các dự án **không cầm key thật** của Anthropic / OpenAI. Mỗi dự án được cấp một key gateway (`pm_llm_…`) có
hạn mức USD theo tháng; gateway thay key thật, chuyển tiếp request và ghi lại token + chi phí.

```
Dự án A ─┐  Authorization: Bearer pm_llm_…      ┌─► api.anthropic.com  (key thật, mã hoá trong DB)
Dự án B ─┼─► https://<domain>/llm/anthropic/... ┤
Dự án C ─┘   https://<domain>/llm/openai/v1/... └─► api.openai.com
             kiểm tra key, model, hạn mức → chọn key nhà cung cấp → chuyển tiếp (kể cả stream) → ghi usage
```

- **Chuyển tiếp nguyên định dạng**: gateway không chuyển đổi request / response, nên SDK chính chủ dùng được ngay,
  đủ mọi tính năng (stream, tool use, ảnh, prompt caching…). Dự án chỉ đổi `base_url` + `api_key`.
- **Không lưu nội dung** prompt / câu trả lời. Chỉ ghi: key dự án, model, số token, chi phí, độ trễ, mã lỗi.
- Chạy **trong container API hiện có** (route `/llm/...`), không thêm service mới.

## 1. Cài đặt trên server

1. Sinh khoá mã hoá và thêm vào `.env` ở thư mục gốc:

   ```bash
   python3 -c "from cryptography.fernet import Fernet; print('LLM_ENCRYPTION_KEY=' + Fernet.generate_key().decode())"
   ```

   **Không đổi khoá này sau khi đã lưu key**: đổi là không giải mã được key cũ, phải nhập lại toàn bộ key nhà
   cung cấp. Backup `.env` cùng với database.

2. Cập nhật code (migration `0015` tự chạy):

   ```bash
   cd /opt/project_manager && git pull && docker compose up -d --build
   ```

3. Nginx thêm `location /llm/` đi **thẳng tới API** (không qua Next.js), tắt buffering để stream mượt —
   xem [DEPLOY.md](DEPLOY.md) mục 6:

   ```nginx
   location /llm/ {
       proxy_pass http://127.0.0.1:8000;   # = PM_API_PORT
       proxy_set_header Host $host;
       proxy_set_header X-Forwarded-For $remote_addr;
       proxy_set_header X-Forwarded-Proto $scheme;
       proxy_http_version 1.1;
       proxy_buffering off;
       proxy_read_timeout 600s;
   }
   ```

   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```

## 2. Cấu hình trong ứng dụng (Quản trị › AI Gateway)

Quyền `llm.manage` (mặc định: admin) để cấu hình; `llm.view` (admin, Quản lý dự án, Ban lãnh đạo) để xem chi phí.

1. **Key nhà cung cấp** › *Thêm key*: chọn Anthropic / OpenAI, dán key. Bấm ⚡ *Kiểm tra key* (gọi thử danh sách
   model). Key chỉ lưu dạng mã hoá, sau đó chỉ thấy `••••a1b2`.
   - Thêm nhiều key cho một nhà cung cấp: ưu tiên cao được dùng trước. Key gặp 429 / 5xx **tạm nghỉ 1 phút**,
     key sai (401 / 403) **tạm nghỉ 10 phút**, gateway tự thử key kế tiếp trong cùng request.
2. **Model & giá** › *Thêm model*: đúng tên model của nhà cung cấp (vd `claude-sonnet-5-5`) và giá
   **USD / 1 triệu token** theo bảng giá của nhà cung cấp (vào, ra, đọc cache, ghi cache). Model không có trong
   danh sách hoặc đang tắt thì gateway từ chối.
3. **Key dự án** › *Cấp key*: tên, dự án, model được dùng (bỏ trống = tất cả), **hạn mức USD / tháng**, giới hạn
   request / phút, ngày hết hạn. Key đầy đủ **chỉ hiện một lần** kèm đoạn code mẫu — copy gửi cho dự án.
   Lộ key thì *Thu hồi* (chặn ngay) rồi cấp key mới.
4. **Sử dụng & chi phí**: chi phí / token theo key dự án (kèm % hạn mức), theo model, theo ngày; danh sách lỗi.

## 3. Dự án dùng thế nào

**Anthropic SDK** (gửi key qua `x-api-key`):

```python
from anthropic import Anthropic

client = Anthropic(base_url="https://<domain>/llm/anthropic", api_key="pm_llm_...")
msg = client.messages.create(model="claude-sonnet-5-5", max_tokens=1024, messages=[{"role": "user", "content": "Xin chào"}])
```

**OpenAI SDK** (gửi key qua `Authorization: Bearer`):

```python
from openai import OpenAI

client = OpenAI(base_url="https://<domain>/llm/openai/v1", api_key="pm_llm_...")
resp = client.chat.completions.create(model="<model OpenAI đã bật>", messages=[{"role": "user", "content": "Xin chào"}])
```

TypeScript / các ngôn ngữ khác tương tự: chỉ đổi `baseURL` + `apiKey`.

| Endpoint gateway | Chuyển tới |
|---|---|
| `POST /llm/anthropic/v1/messages`, `…/messages/count_tokens` | `api.anthropic.com/v1/...` |
| `POST /llm/openai/v1/chat/completions`, `/responses`, `/embeddings`, `/completions` | `api.openai.com/v1/...` |
| `GET /llm/{anthropic\|openai}/v1/models` | Danh sách model key này được dùng |

Lỗi của gateway trả theo **định dạng của nhà cung cấp** để SDK hiển thị đúng:

| Mã | Khi nào |
|---|---|
| 401 | Thiếu key, key sai, đã thu hồi hoặc hết hạn |
| 400 | Model chưa được bật trên gateway |
| 403 | Key không được dùng model này |
| 429 | Vượt giới hạn request / phút, hoặc **đã dùng hết hạn mức tháng** |
| 502 / 503 | Không gọi được nhà cung cấp / chưa có key nhà cung cấp nào sẵn sàng |

## 4. Cách tính chi phí và hạn mức

- Chi phí một request = (token vào × giá vào + token ra × giá ra + token đọc cache × giá đọc cache + token ghi
  cache × giá ghi cache) / 1.000.000. Giá cache bỏ trống thì tính như giá vào.
- Token đọc từ phản hồi: JSON thường, hoặc sự kiện stream (Anthropic `message_start` / `message_delta`; OpenAI
  chunk cuối — gateway tự bật `stream_options.include_usage` cho chat completions có stream).
- Hạn mức tính theo **tháng dương lịch, giờ Việt Nam**. Kiểm tra **trước** mỗi request: đã dùng ≥ hạn mức thì
  chặn. Các request đang chạy dở lúc chạm hạn mức vẫn hoàn tất, nên có thể vượt hạn mức một chút.
- Giới hạn request / phút đếm trong bộ nhớ của container API (một process). Khởi động lại API thì đếm lại.

## 5. Bảo mật

- Key nhà cung cấp mã hoá bằng Fernet (AES) với `LLM_ENCRYPTION_KEY`; API không bao giờ trả lại key thật.
- Key dự án chỉ lưu SHA-256 (như token PAT).
- Thêm / sửa / xoá key nhà cung cấp, cấp / sửa / thu hồi key dự án đều ghi vào **Nhật ký hệ thống** (không kèm
  giá trị key).
- Gateway không lưu nội dung prompt / câu trả lời.

## Xử lý sự cố

| Triệu chứng | Nguyên nhân / cách xử lý |
|---|---|
| Trang AI Gateway báo chưa cấu hình `LLM_ENCRYPTION_KEY` | Thiếu biến trong `.env`, hoặc chưa `docker compose up -d` lại |
| Gọi `/llm/...` trả trang HTML của web | Thiếu `location /llm/` trong nginx (request đang đi vào Next.js) |
| Stream trả về một lần ở cuối thay vì từng chữ | nginx thiếu `proxy_buffering off` |
| Mọi request 503 "chưa có key … sẵn sàng" | Chưa thêm key, key đang tắt, hoặc mọi key đang tạm nghỉ (xem cột *Lỗi gần nhất*, bấm ⚡ để kiểm tra) |
| "Không giải mã được key: LLM_ENCRYPTION_KEY đã bị đổi?" | Khoá mã hoá khác lúc lưu key: khôi phục khoá cũ, hoặc nhập lại key nhà cung cấp |
| Chi phí hiện 0 | Model chưa nhập giá |
