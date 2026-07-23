# Security và threat model

## Tài sản cần bảo vệ

- JWT, application secret, OpenAI key và database credentials.
- Dữ liệu order, warranty, conversation, feedback và ticket của từng user.
- Tính đúng đắn của giá, tồn kho và policy.
- Knowledge base đã publish và lịch sử version.
- Log/metric không được trở thành kênh rò rỉ PII hoặc token.

## Trust boundaries

| Boundary | Dữ liệu được tin |
|---|---|
| Browser → API | Không tin; validate toàn bộ |
| JWT dependency → service | Tin identity sau khi verify chữ ký/expiry/user active |
| Retrieved document → model | Chỉ là data, không phải instruction |
| Model output → user | Chưa tin cho tới khi qua output verifier |
| Repository → database | Query tham số hóa, giới hạn row và ownership |

## Mối đe doạ và control

| Threat | Control hiện có |
|---|---|
| Cross-customer order/warranty access | User ID chỉ từ JWT; repository lọc ownership; integration test |
| Model tự gọi tool khác | Router trả allowlist; orchestrator không expose raw SQL |
| Prompt injection trong user/document | System policy cố định; document là data; security eval; output verifier |
| Fake tool result | Typed result và tool trace; failure không được tổng hợp thành success |
| Chính sách thiếu/conflict | No-evidence/conflict fallback và human review |
| Upload độc hại | Extension + media type + magic bytes + size/page limit + sanitized filename |
| Secret/PII trong log | Structured allowlist logging; redactor email/phone/token/key/card |
| Token replay/brute force | JWT expiry, active-user check và auth rate limit |
| Request ID log injection | Regex allowlist và giới hạn 64 ký tự |
| Clickjacking/MIME sniffing | CSP, `frame-ancestors`, `X-Frame-Options`, `nosniff` |
| Unsupported refund/warranty promise | Output verifier và human handoff rules |
| Citation gắn sai claim | Label allowlist + lexical claim/source support guard |
| Unbounded tool/model call | Max tool calls, per-tool timeout và request timeout |
| Retention vô hạn | 30 ngày mặc định, background cleanup và admin-triggered cleanup |

## Authentication và authorization

- Mật khẩu hash bằng Argon2 qua `pwdlib`.
- JWT chứa identity đã ký; service không nhận `user_id` từ request body/tool args.
- `customer`, `support`, `admin` là enum role.
- Upload/publish/archive và retention manual chỉ dành cho admin. Metrics cùng
  hàng đợi escalation/ticket chỉ dành cho support/admin và giới hạn 50 mục.
- Conversation, message feedback và delete luôn scope theo authenticated owner.
- Web workflow dùng role PostgreSQL `app_runtime` không có superuser/createdb/
  createrole/DDL. Catalog/order/warranty/retrieval tools dùng `app_agent` chỉ có
  SELECT; ticket side effect đi qua service runtime ràng buộc. Migration/provision
  dùng credential thứ ba tách biệt.

Không yêu cầu password, OTP, full card number hoặc secret qua chat. Không trả
stack trace hoặc tên tool nội bộ cho khách.

## Secret management

`.env` bị gitignore. Production secret chỉ đặt trong Railway sealed variables.
`APP_ENV=production` từ chối secret mặc định/rỗng và tắt OpenAPI docs. Không đặt
secret vào `VITE_*` vì mọi biến Vite đều được bundle vào browser.

Migration credential và mật khẩu tạo role chỉ tồn tại trong pre-deploy. Entrypoint
loại `MIGRATION_DATABASE_URL`, `RUNTIME_DB_PASSWORD` và `AGENT_DB_PASSWORD` khỏi
môi trường Uvicorn trước khi web process chạy; runtime chỉ giữ hai URL ít quyền.

Quy trình rotate:

1. Tạo secret mới trong secret manager.
2. Cập nhật biến mà không in giá trị vào log.
3. Redeploy backend.
4. Với JWT secret, chấp nhận mọi phiên cũ hết hiệu lực và thông báo đăng nhập lại.
5. Revoke key cũ sau khi health/smoke pass.

## Logging policy

Log chỉ gồm event name, route template, method, status class, latency, request ID,
intent, tool name, citation count và error code/type. Không log:

- request/response body;
- query string;
- authorization/cookie;
- raw user ID, email, phone, order content;
- prompt, chain-of-thought, document body;
- database URL hoặc provider key.

Redactor là lớp phòng vệ thứ hai, không thay thế allowlist logging.

## Security headers

Backend và Nginx đều đặt CSP, `nosniff`, `DENY`, `no-referrer`,
`Permissions-Policy` và `no-store`. Backend thêm HSTS ở production. CORS chỉ nhận
danh sách origin cấu hình; không dùng wildcard với credential.

## Risk còn lại

- In-memory limiter không đồng bộ giữa replica và reset khi restart.
- JWT chưa có server-side revocation list.
- Local persistent volume cần process khởi động bằng root trên Railway để chown,
  sau đó entrypoint hạ quyền về UID/GID 10001.
- Antivirus/CDR cho PDF chưa có ở V1; file vẫn phải được lấy từ nguồn quản trị
  được phê duyệt.
- LLM/embedding là external processor; production phải ký DPA và cấu hình data
  handling phù hợp.
- Metrics endpoint là snapshot process, chưa thay thế central monitoring/audit
  log bất biến.
- Citation support guard kiểm tra từng câu, từng mệnh đề và từng lần dùng label:
  mỗi mệnh đề phải có ít nhất một source hỗ trợ, mỗi source gắn vào phải hỗ trợ
  ít nhất một mệnh đề, polarity phủ định và mọi số liệu phải khớp. Ở cấp mệnh đề,
  guard yêu cầu ≥2 term không-generic và ≥70% term có trong source. Đây vẫn là
  lexical defense. Bộ gold cân bằng kiểm regression với citation-validity gate
  100%, nhưng không thay thế reviewer faithfulness trên output provider.

## Khi nào bắt buộc human review

Safety issue, pin cháy/nổ, nghi data breach, đe doạ, tranh chấp pháp lý, bảo hành
cần kiểm tra vật lý, evidence conflict/outdated, repeated failure hoặc bất kỳ
trường hợp nào backend không đủ bằng chứng. AI không tự mark complaint resolved.
