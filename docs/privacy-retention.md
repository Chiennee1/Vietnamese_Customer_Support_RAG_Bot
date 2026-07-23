# Privacy và data retention

## Nguyên tắc

- Data minimization: chỉ thu thập/hiển thị trường cần cho yêu cầu CSKH.
- Purpose limitation: không dùng conversation/order/warranty cho mục đích khác
  nếu chưa có cơ sở và thông báo phù hợp.
- Access control: identity từ runtime, không từ text người dùng.
- Accuracy: live commerce data từ DB; policy từ published knowledge.
- Human oversight: AI không tự phê duyệt quyền lợi hoặc đóng complaint.

Portfolio dataset là synthetic. Trước khi dùng dữ liệu thật phải có privacy notice,
legal basis/consent phù hợp, DPA với provider và quy trình data-subject request.

## Data inventory

| Data | Mục đích | Hiển thị tối thiểu | Retention V1 |
|---|---|---|---|
| User account | Auth/ownership | Tên, email của chính user | Theo account policy |
| Order/warranty | Support lookup | Code/status/date, địa chỉ masked | Theo business/legal policy |
| Conversation/message | Continuity, QA | Chỉ owner/support được phép | 30 ngày mặc định |
| Tool execution | Audit/debug | Tool/status/duration, không body | Theo conversation |
| Feedback | Quality | Rating + comment tự nguyện | Theo message/conversation |
| Ticket | Human support | Summary tối thiểu | Theo complaint policy |
| Knowledge document | Policy evidence | Public business content | Theo version/audit policy |
| Logs/metrics | Reliability/security | Không body/token/raw PII | Cấu hình central log riêng |
| Upload original | Reprocess/audit | Admin only | Theo document lifecycle |

## Conversation deletion

User có thể xoá từng conversation. Repository chỉ xoá khi `conversation.user_id`
trùng identity. Foreign key cascade xoá message/tool execution/feedback liên quan.
Background retention xoá conversation quá cutoff theo batch. Ticket không được AI
tự mark resolved; retention của ticket phải theo policy hỗ trợ riêng.

Admin manual retention:

```text
POST /api/v1/admin/retention/run
```

Endpoint không nhận user ID/cutoff tuỳ ý, tránh biến thành privileged delete tool.

## Response minimization

- Không trả full địa chỉ, password hash, token, provider/database identifiers.
- Không hiển thị dữ liệu người khác dù user cung cấp order code/serial hợp lệ.
- Không lặp lại dữ liệu nhạy cảm không cần thiết trong complaint summary.
- Không yêu cầu password, OTP, full payment-card number hoặc API secret.
- Giữ nguyên exact SKU/order/serial/date/price khi thật sự cần.

## Logs và analytics

Không log prompt/body, email, phone, token, cookie, document text hoặc chain of
thought. Nếu cần phân tích top query:

1. redaction trước khi export;
2. bỏ exact identifier và rare phrase;
3. aggregate/k-anonymize;
4. giới hạn quyền truy cập và retention;
5. không tái nhận dạng user.

## Data-subject request

Quy trình production đề xuất:

1. Human xác minh danh tính ngoài chat, không hỏi secret/OTP trong chat.
2. Xác định hệ thống/record trong scope.
3. Export/delete/correct theo policy và legal hold.
4. Ghi audit tối thiểu, không đưa dữ liệu vào public ticket.
5. Xác nhận hoàn tất bởi người có thẩm quyền.

AI chỉ hướng dẫn/handoff, không tự quyết định hoặc xác nhận request đã hoàn tất.

## Thay đổi retention

Thay đổi `CONVERSATION_RETENTION_DAYS` là thay đổi privacy policy:

- có approval;
- test trên staging với backup;
- thông báo nếu nghĩa vụ yêu cầu;
- không tăng vô hạn vì mục đích debug;
- ghi release note và review central log/provider retention tương ứng.
