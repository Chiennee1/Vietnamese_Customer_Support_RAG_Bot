# API contract

Base path: `/api/v1`. JSON request dùng `Content-Type: application/json`; endpoint
cần auth dùng `Authorization: Bearer <JWT>`. Client có thể gửi `X-Request-ID`
gồm chữ/số/`._:-`, tối đa 64 ký tự; giá trị không hợp lệ bị thay bằng UUID.

## Endpoint

| Method | Path | Auth | Mục đích |
|---|---|---|---|
| POST | `/auth/register` | Public, rate-limited | Tạo customer account |
| POST | `/auth/login` | Public, rate-limited | Nhận JWT |
| GET | `/auth/me` | User | Runtime identity |
| POST | `/chat` | User | Chat response đầy đủ |
| POST | `/chat/stream` | User | SSE `meta` → `delta` → `done` |
| GET | `/conversations` | User | Conversation của chính user |
| GET | `/conversations/{id}` | Owner | Messages/citations |
| DELETE | `/conversations/{id}` | Owner | Xoá conversation |
| POST | `/feedback` | Owner | Upsert feedback cho assistant message |
| POST | `/documents` | Admin | Upload Markdown/PDF, trả 202 |
| GET | `/documents` | Admin | Liệt kê document |
| GET | `/documents/{id}` | Admin | Document detail/status |
| POST | `/documents/{id}/retry` | Admin | Retry failed ingestion, trả 202 |
| POST | `/documents/{id}/publish` | Admin | Publish ready version |
| POST | `/documents/{id}/archive` | Admin | Archive version |
| GET | `/admin/metrics` | Admin | Operational snapshot |
| POST | `/admin/retention/run` | Admin | Chạy retention với configured cutoff |
| GET | `/health/live` | Public | Process liveness |
| GET | `/health/ready` | Public | Database readiness |

## Chat

Request:

```json
{
  "conversation_id": null,
  "message": "Đơn DH2026000001 đang ở đâu?"
}
```

`conversation_id` có thể bỏ/null để tạo conversation. Message 1–2.000 ký tự,
extra field bị từ chối.

Response shape:

```json
{
  "conversation_id": "uuid",
  "message_id": "uuid",
  "answer": "Câu trả lời tiếng Việt",
  "intent": "order_status",
  "citations": [],
  "requires_human": false,
  "human_reason": null,
  "suggested_actions": [],
  "ticket_code": null
}
```

Citation gồm `label`, `document_id`, `chunk_id`, `title`, `version`,
`section_path`, `page` và `excerpt`. Commerce-only answer không tạo citation giả.

SSE:

```text
event: meta
data: {"conversation_id":"...","message_id":"..."}

event: delta
data: {"text":"..."}

event: done
data: {"intent":"...","citations":[],"requires_human":false,...}
```

`delta` chỉ được phát sau khi backend đã hoàn tất tool/model, verify và persist
câu trả lời; đây không phải raw provider token stream.

## Document upload

`multipart/form-data`:

- `title`: 2–240 ký tự;
- `version`: 1–40;
- `category`: 2–80;
- `effective_from`, `effective_to`: datetime tuỳ chọn;
- `file`: Markdown/PDF trong limit cấu hình.

Trạng thái: `uploaded` → `processing` → `ready` → `published` → `archived`, hoặc
`failed` rồi `retry`. `202` chỉ xác nhận nhận job, không đồng nghĩa publish.

## Feedback

```json
{
  "message_id": "uuid",
  "rating": "positive",
  "comment": "Trích dẫn đúng và dễ hiểu."
}
```

Rating theo enum backend (`positive`/`negative`); comment tối đa 1.000 ký tự.
User không thể feedback message của conversation người khác.

## Error envelope

Application error:

```json
{
  "error": {
    "code": "CONVERSATION_NOT_FOUND",
    "message": "Thông báo an toàn bằng tiếng Việt"
  },
  "request_id": "uuid-or-approved-client-id"
}
```

Không suy luận existence của record không được phép. `401` yêu cầu đăng nhập,
`403` thiếu role, `404` không tìm thấy trong accessible data, `429` có
`Retry-After`, `503` dependency chưa ready và `504` request/tool timeout.

OpenAPI UI chỉ bật ở development/test. Production cố ý trả 404 cho `/docs` và
`/openapi.json`.
