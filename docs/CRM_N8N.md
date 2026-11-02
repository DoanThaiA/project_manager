# Tích hợp n8n (Gmail) với CRM dự án

n8n đọc Gmail, nhờ AI trích xuất thông tin khách và nhu cầu, rồi gửi từng email sang CRM của một dự án.
CRM gộp các email theo người gửi thành **khách liên hệ** để đội theo dõi (trạng thái, người phụ trách, ghi chú)
ở tab **CRM** trong dự án.

```
Gmail ─► n8n: Gmail Trigger ─► AI trích xuất ─► IF có phải khách hỏi mua? ─► Code (tạo payload)
                                                                              │
                     POST /api/v1/projects/{pid}/crm/emails/ingest ◄──────────┘
                     Authorization: Bearer pm_pat_...
```

- n8n gửi lại cùng email (retry, chạy lại workflow) thì **không tạo trùng**: khoá chống trùng là `email_message_id`.
- Email của cùng người gửi (`customer_email`) gộp vào một khách; thông tin AI trích xuất chỉ điền vào các trường
  khách **còn trống**, không ghi đè những gì nhân viên đã sửa tay.

## 1. Cập nhật server (migration 0012)

```bash
cd /opt/project_manager
git pull
docker compose up -d --build
```

Container API tự chạy `alembic upgrade head` khi khởi động. Nên backup database trước (DEPLOY.md mục 7). Kiểm tra:

```bash
docker compose exec api alembic current      # phải thấy 0012 (head)
docker compose logs --tail=50 api            # không có lỗi alembic
```

Mở một dự án trên web: thấy tab **CRM** (đăng nhập bằng admin / PO / BA / Quản lý dự án).

## 2. Lấy mã dự án (`project_id`)

Mở dự án trên web, số trên URL là mã dự án: `https://<domain>/projects/3/...` → `project_id = 3`.

Mỗi dự án có CRM riêng. Nhiều dự án (nhiều thương hiệu / hộp thư) thì xem mục 8.

## 3. Tạo tài khoản bot cho n8n

Không dùng tài khoản cá nhân: token của n8n mang toàn bộ quyền của tài khoản sở hữu, và nhật ký sẽ ghi thay đổi
dưới tên tài khoản đó.

1. **Tạo vai trò dự án chỉ có quyền nhận email** (khuyên dùng, quyền tối thiểu): admin vào **Quản trị › Vai trò & quyền**
   → tạo vai trò mã `CRM_BOT`, tên "Bot CRM", phạm vi **Dự án** → chỉ tick `crm.create`.
   Cách nhanh hơn: dùng vai trò **BA** có sẵn (có `crm.create`, nhưng cũng tạo / sửa được yêu cầu, công việc).
2. **Tạo người dùng**: **Quản trị › Người dùng** → username `bot.n8n`, email bất kỳ của công ty, mật khẩu mạnh.
   Không gán vai trò hệ thống.
3. **Thêm vào dự án**: vào dự án › **Thành viên** → thêm `bot.n8n` với vai trò `Bot CRM` (hoặc BA).
   Mỗi dự án n8n cần ghi vào đều phải thêm bot.

## 4. Tạo token truy cập (PAT)

Token tạo qua API (chưa có màn hình). Chạy trên máy bất kỳ gọi được tới server, thay `<domain>`:

```bash
API=https://<domain>/api/v1
```

Đăng nhập bằng bot để lấy JWT (nhập mật khẩu bot khi được hỏi):

```bash
read -rsp "Mật khẩu bot.n8n: " PW; echo; JWT=$(curl -s -X POST "$API/auth/login" --data-urlencode "username=bot.n8n" --data-urlencode "password=$PW" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])"); unset PW
```

Tạo PAT hạn 365 ngày (tối đa):

```bash
curl -s -X POST "$API/me/api-tokens" -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" -d '{"name": "n8n Gmail CRM", "expires_days": 365}'
```

Kết quả có trường `"token": "pm_pat_..."` — **chỉ hiện một lần**, lưu ngay vào credential của n8n (mục 6.1).
Database chỉ giữ bản băm, mất token thì tạo token mới.

Quản lý token (vẫn dùng JWT của bot):

```bash
curl -s "$API/me/api-tokens" -H "Authorization: Bearer $JWT"
```

```bash
curl -s -X DELETE "$API/me/api-tokens/<id>" -H "Authorization: Bearer $JWT"
```

Ghi lịch nhắc **trước ngày hết hạn**: hết hạn thì n8n nhận 401 và email không vào CRM.

## 5. Thử endpoint bằng curl (trước khi làm n8n)

```bash
PAT=pm_pat_...; PID=3
```

```bash
curl -s -X POST "$API/projects/$PID/crm/emails/ingest" -H "Authorization: Bearer $PAT" -H "Content-Type: application/json" -d '{"email_message_id": "test-001", "received_at": "2026-10-31T09:15:00+07:00", "subject": "Thử tích hợp n8n", "customer_email": "Khách Thử <khach.thu@example.com>", "customer_name": "Khách Thử", "inquiry_type": "bao_gia", "product_type": "Túi giấy kraft", "quantity": "1.000 cái", "summary": "Email thử tích hợp"}'
```

- Lần 1: `{"lead_id": ..., "contact_id": ..., "created": true}`, tab CRM có khách "Khách Thử".
- Chạy lại y hệt: `"created": false` — chống trùng hoạt động.
- Xong thì xoá khách "Khách Thử" trên giao diện (nút **Xoá khách** trong chi tiết khách).

## 6. Dựng workflow n8n

### 6.1. Credential

**Credentials › Add credential › Header Auth**:

| Trường | Giá trị |
|---|---|
| Name | `Authorization` |
| Value | `Bearer pm_pat_...` (có chữ `Bearer` và một dấu cách) |

### 6.2. Node 1 — Gmail Trigger

| Thiết lập | Giá trị |
|---|---|
| Credential | Gmail OAuth2 của hộp thư nhận khách |
| Poll Times | Every Minute (hoặc 5 phút) |
| Event | Message Received |
| **Simplify** | **Tắt** — để có nội dung đầy đủ (`text`) và người gửi dạng có cấu trúc (`from.value[0]`) |
| Filters › Search | `in:inbox -from:me -category:promotions -category:social` (bỏ thư mình gửi, quảng cáo) |

Gmail Trigger chỉ lấy email **mới** kể từ khi bật workflow. Email cũ: xem mục 7.

Bấm **Fetch Test Event**, xem output để chắc chắn tên trường (`id`, `threadId`, `date`, `subject`, `text`,
`from.value[0].address`, `from.value[0].name`). Tên trường có thể khác chút theo phiên bản n8n — chỉnh lại
biểu thức ở node Code (6.5) cho khớp.

### 6.3. Node 2 — AI trích xuất

Dùng node **Information Extractor** (nhóm AI, gắn một Chat Model: Anthropic Claude / OpenAI…) hoặc một
**Basic LLM Chain** có output parser JSON. Đầu vào:

```
Người gửi: {{ $json.from.text }}
Tiêu đề: {{ $json.subject }}
Nội dung:
{{ ($json.text || '').slice(0, 8000) }}
```

System prompt:

```
Bạn đọc email gửi tới công ty bao bì và trích xuất thông tin khách hàng tiềm năng.
- is_lead = true chỉ khi người gửi hỏi mua, xin báo giá, đặt hàng hoặc hỏi thông tin sản phẩm/dịch vụ.
  Quảng cáo, thông báo hệ thống, hoá đơn, nhà cung cấp chào hàng, thư nội bộ -> is_lead = false.
- inquiry_type: dat_hang (đặt hàng) | bao_gia (xin báo giá) | hoi_thong_tin (hỏi thông tin) | khac.
- Giữ nguyên văn khách viết cho product_type, quantity, specifications, budget, deadline (không quy đổi).
- Không có thông tin thì để chuỗi rỗng, không bịa.
- summary: 1 câu tiếng Việt tóm tắt nhu cầu.
- ai_confidence: 0..1, mức chắc chắn của bạn.
```

Schema output (JSON Schema, dán vào Information Extractor › *Define using JSON Schema*):

```json
{
  "type": "object",
  "properties": {
    "is_lead": { "type": "boolean" },
    "customer_name": { "type": "string" },
    "contact_email": { "type": "string", "description": "Email liên hệ khác ghi trong nội dung, nếu có" },
    "phone": { "type": "string" },
    "company": { "type": "string" },
    "address": { "type": "string" },
    "inquiry_type": { "type": "string", "enum": ["dat_hang", "bao_gia", "hoi_thong_tin", "khac"] },
    "product_type": { "type": "string" },
    "quantity": { "type": "string" },
    "specifications": { "type": "string" },
    "budget": { "type": "string" },
    "deadline": { "type": "string" },
    "summary": { "type": "string" },
    "ai_confidence": { "type": "number" }
  },
  "required": ["is_lead", "inquiry_type"]
}
```

### 6.4. Node 3 — IF

Điều kiện: `{{ $json.output.is_lead }}` **is true** (Information Extractor trả kết quả trong `output`; dùng node khác
thì bỏ `.output`). Nhánh false: kết thúc, không gửi CRM.

### 6.5. Node 4 — Code (tạo payload)

Mode **Run Once for Each Item**, ngôn ngữ JavaScript. `'Gmail Trigger'` phải trùng tên node Gmail trong workflow.

```javascript
const mail = $('Gmail Trigger').item.json;
const ai = $json.output ?? $json;
const sender = mail.from?.value?.[0] ?? {};

return {
  json: {
    // Gmail
    email_message_id: mail.id,
    email_thread_id: mail.threadId,
    received_at: new Date(mail.date ?? Date.now()).toISOString(),
    subject: mail.subject ?? '',
    content: (mail.text ?? '').slice(0, 8000),
    // Khách: email lấy từ header Gmail, phần còn lại từ AI
    customer_email: sender.address ?? '',
    customer_name: ai.customer_name || sender.name || '',
    contact_email: ai.contact_email ?? '',
    phone: ai.phone ?? '',
    company: ai.company ?? '',
    address: ai.address ?? '',
    // Nhu cầu
    inquiry_type: ai.inquiry_type ?? 'khac',
    product_type: ai.product_type ?? '',
    quantity: ai.quantity ?? '',
    specifications: ai.specifications ?? '',
    budget: ai.budget ?? '',
    deadline: ai.deadline ?? '',
    summary: ai.summary ?? '',
    ai_confidence: ai.ai_confidence ?? null,
    source: 'gmail',
  },
};
```

### 6.6. Node 5 — HTTP Request (gửi CRM)

| Thiết lập | Giá trị |
|---|---|
| Method | `POST` |
| URL | `https://<domain>/api/v1/projects/3/crm/emails/ingest` (thay `3` bằng mã dự án) |
| Authentication | Generic Credential Type › **Header Auth** › credential ở 6.1 |
| Send Body | Bật, Body Content Type **JSON**, Specify Body **Using JSON**, JSON: `{{ $json }}` |
| Settings › Retry On Fail | Bật, Max Tries `3`, Wait Between Tries `5000` ms |
| Settings › On Error | *Continue (using error output)* → nối nhánh lỗi sang node gửi Telegram / email cảnh báo (tuỳ chọn) |

n8n chạy **cùng server** với Project Manager thì có thể gọi thẳng API, khỏi qua nginx:
`http://127.0.0.1:${PM_API_PORT}/api/v1/projects/3/crm/emails/ingest` (n8n chạy trong Docker thì dùng IP host
hoặc cho n8n vào cùng mạng docker và gọi `http://api:8000/...`).

### 6.7. (Tuỳ chọn) Node 6 — Gắn nhãn Gmail

Gmail › **Add Label to Message**, Message ID `{{ $('Gmail Trigger').item.json.id }}`, nhãn `CRM` — nhìn hộp thư
biết email nào đã vào CRM.

### 6.8. Chạy thử và bật

1. Gửi một email hỏi giá thật từ hộp thư khác tới hộp thư nhận khách.
2. **Execute Workflow**, xem từng node; node HTTP trả `"created": true`.
3. Mở tab **CRM** của dự án: có khách mới, bấm vào thấy email kèm nhu cầu AI trích xuất.
4. Gửi thêm một email quảng cáo: phải dừng ở nhánh false của IF.
5. Bật **Active** cho workflow.

## 7. Nạp email cũ (tuỳ chọn)

Tạo workflow phụ: **Manual Trigger → Gmail › Get Many Messages** (Simplify tắt, Search ví dụ
`in:inbox after:2026/09/01 -from:me`, Limit vừa phải) → nối tiếp các node 6.3–6.6 như trên (đổi `'Gmail Trigger'`
trong node Code thành tên node Get Many). Chạy lại bao nhiêu lần cũng không trùng nhờ `email_message_id`.

## 8. Nhiều dự án / nhiều hộp thư

- **Mỗi hộp thư một dự án**: nhân bản workflow, đổi credential Gmail và mã dự án trong URL node HTTP.
- **Một hộp thư, chia theo nhãn Gmail**: trước node HTTP thêm **Switch** theo nhãn (`labelIds`) hoặc theo nội dung,
  mỗi nhánh một node HTTP với mã dự án khác nhau.
- Bot phải là thành viên (vai trò có `crm.create`) của **mọi** dự án được ghi.

## 9. Sử dụng CRM trên web

Tab **CRM** trong dự án (cần quyền `crm.view`):

- Thống kê: số khách, email 7 ngày, khách đang mở chưa có người phụ trách, chốt đơn.
- **Khách liên hệ**: lọc trạng thái / nhu cầu / người phụ trách, tìm theo tên, email, công ty, SĐT.
- **Email nhận được**: toàn bộ email theo thời gian, lọc theo nhu cầu, khoảng ngày.
- Chi tiết khách: đổi trạng thái (Mới → Đã liên hệ → Đã báo giá → Đang thương lượng → Chốt đơn / Không thành / Spam),
  giao người phụ trách, ghi chú, xem từng email (nội dung gốc, trả lời, mở trong Gmail).
- Khách gửi spam: chuyển trạng thái **Spam** (đừng xoá — xoá rồi email sau của họ lại tạo khách mới).

| Vai trò | Quyền CRM |
|---|---|
| SYSTEM_ADMIN, PROJECT_MANAGER, PRODUCT_OWNER | Xem, thêm, sửa, xoá |
| BA | Xem, thêm, sửa |
| SCRUM_MASTER, EXECUTIVE | Chỉ xem |
| DEVELOPER, TESTER, VIEWER, CUSTOMER | Không thấy CRM |

## 10. Payload & phản hồi

| Trường | Bắt buộc | Ghi chú |
|---|---|---|
| `email_message_id` | ✔ | Mã email Gmail, ≤ 100 ký tự, chống trùng trong dự án |
| `received_at` | ✔ | ISO 8601; không có múi giờ thì coi là giờ Việt Nam |
| `customer_email` | ✔ | Email người gửi; nhận cả dạng `Tên <email>`, tự chuyển chữ thường |
| `inquiry_type` | | `dat_hang` / `bao_gia` / `hoi_thong_tin` / `khac`; giá trị lạ → `khac` |
| `ai_confidence` | | 0..1; ngoài khoảng thì kẹp lại, `""` → trống |
| Các trường khác | | `email_thread_id`, `subject`, `content`, `customer_name`, `contact_email`, `phone`, `company`, `address`, `product_type`, `quantity`, `specifications`, `budget`, `deadline`, `summary`, `source`; `""` → trống, quá dài thì cắt cho vừa cột |

Phản hồi `200`: `{"lead_id": 12, "contact_id": 5, "created": true}` — `created: false` nghĩa là email đã có, không tạo mới.

## 11. Xử lý sự cố

| Phản hồi | Nguyên nhân / cách xử lý |
|---|---|
| `401 Không thể xác thực thông tin đăng nhập` | Token sai, thiếu chữ `Bearer `, đã hết hạn hoặc bị thu hồi → tạo token mới (mục 4) |
| `403 Tài khoản đã bị khoá hoặc ngừng hoạt động` | Tài khoản bot bị khoá → mở khoá ở Quản trị › Người dùng |
| `403 Yêu cầu quyền 'crm.create' trong dự án` | Bot chưa là thành viên dự án, hoặc vai trò thiếu `crm.create` (mục 3) |
| `404 Không tìm thấy dự án` | Sai mã dự án trong URL, hoặc dự án đã xoá |
| `422` | Thiếu `email_message_id` / `received_at` / `customer_email`, hoặc `customer_email` không phải email hợp lệ → xem output node Code |
| `502` / `504` | Server / nginx chưa chạy — `docker compose ps`, `docker compose logs api web` |
| Luôn `created: false` | `email_message_id` bị cố định (vd: test-001) thay vì lấy `{{ id }}` của Gmail |
| Khách bị tách đôi | Cùng một người nhưng gửi từ 2 email khác nhau — CRM gộp theo email người gửi; sửa tay nếu cần |

Kiểm tra thủ công: lặp lại lệnh curl ở mục 5 với token đang dùng trong n8n.
