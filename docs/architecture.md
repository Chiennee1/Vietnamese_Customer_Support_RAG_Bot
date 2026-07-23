# Kiến trúc hệ thống

## Mục tiêu thiết kế

Hệ thống tách ba loại quyết định:

1. Backend xác thực và cấp runtime identity.
2. Router/orchestrator quyết định workflow trong tập tool cho phép.
3. Repository thực thi query tham số hóa và luôn áp ownership ở tầng dữ liệu.

LLM chỉ tổng hợp từ kết quả tool và evidence. Nó không phải nguồn sự thật cho dữ
liệu cửa hàng, không nhận raw SQL và không được tự tạo user ID.

## Deployment view

```mermaid
flowchart TB
    subgraph Browser
        UI[React + Vite SPA]
    end

    subgraph Backend container
        MW[CORS / request ID / rate limit / headers]
        AUTH[JWT authentication]
        API[FastAPI routes]
        CHAT[Chat service]
        ROUTER[Intent router]
        ORCH[Support orchestrator]
        VERIFY[Output verifier]
        INGEST[Ingestion lifecycle]
        RETAIN[Retention worker]
        METRIC[Process metrics]
    end

    subgraph Data
        PG[(PostgreSQL 16)]
        VECTOR[(pgvector HNSW)]
        FILES[(Upload volume)]
    end

    subgraph Provider
        OPENAI[OpenAI chat + embeddings]
    end

    UI --> MW --> AUTH --> API --> CHAT
    CHAT --> ROUTER --> ORCH
    ORCH --> PG
    ORCH --> VECTOR
    ORCH --> OPENAI
    ORCH --> VERIFY --> CHAT
    API --> INGEST --> FILES
    INGEST --> OPENAI
    INGEST --> PG
    RETAIN --> PG
    MW --> METRIC
```

## Luồng chat

```mermaid
sequenceDiagram
    participant U as User
    participant API as FastAPI
    participant S as ChatService
    participant R as Router
    participant O as Orchestrator
    participant T as Constrained tools
    participant DB as PostgreSQL/pgvector
    participant M as Model

    U->>API: POST /api/v1/chat + JWT
    API->>API: Xác thực, rate limit, request ID
    API->>S: user_id từ trusted runtime
    S->>R: message
    R-->>O: intent + allowed_tools
    O->>T: Chỉ tool được phép
    T->>DB: Query tham số hóa + ownership
    DB-->>T: Live data / published evidence
    T-->>O: Typed result
    O->>M: Evidence + tool result, không có secret
    M-->>O: Draft answer
    O->>O: Verify citations, promise, PII, injection
    O-->>S: Answer + citations + handoff
    S->>DB: Persist messages/tool traces
    S-->>API: Response / SSE events
    API-->>U: Câu trả lời trực tiếp
```

Với lời chào và một số safe failure deterministic, model không được gọi. Với
policy, chỉ chunk của document `published`, đúng effective window và không bị
archive mới được retrieve.

## Luồng ingestion

```mermaid
stateDiagram-v2
    [*] --> uploaded
    uploaded --> processing
    processing --> ready: parse + normalize + chunk + embed thành công
    processing --> failed: bất kỳ bước nào lỗi
    failed --> processing: admin retry
    ready --> published: admin review và publish
    published --> archived: admin archive / version mới
    archived --> [*]
```

Checksum ngăn upload trùng. Chunk và trạng thái document được ghi transactionally;
không có partial document được publish. File chỉ nhận Markdown/PDF đã kiểm tra
magic bytes, kích thước, số trang và tên file.

## Data model chính

```mermaid
erDiagram
    USERS ||--o{ ORDERS : owns
    USERS ||--o{ WARRANTIES : owns
    USERS ||--o{ CONVERSATIONS : owns
    USERS ||--o{ SUPPORT_TICKETS : creates
    PRODUCTS ||--o{ PRODUCT_VARIANTS : has
    PRODUCT_VARIANTS ||--o{ INVENTORY : stocked
    ORDERS ||--|{ ORDER_ITEMS : contains
    ORDER_ITEMS ||--o| WARRANTIES : covers
    CONVERSATIONS ||--|{ MESSAGES : contains
    MESSAGES ||--o{ TOOL_EXECUTIONS : traces
    MESSAGES ||--o| FEEDBACK : receives
    KNOWLEDGE_DOCUMENTS ||--o{ KNOWLEDGE_CHUNKS : contains
```

Mọi khoá, SKU, order code, serial, thời gian và giá được giữ nguyên ở output.
Địa chỉ giao hàng chỉ lưu/render dạng masked trong dataset demo.

## Module boundaries

- `api`: HTTP contract, authentication dependency và role check.
- `services`: use case, timeout tổng, persistence workflow.
- `ai`: router, provider abstraction, RAG, tool registry, output verifier.
- `repositories`: query SQLAlchemy tham số hóa và data ownership.
- `storage`: file persistence; không chứa business rule.
- `evaluation`: deterministic release gate.

Router dùng typed deterministic decision thay cho LLM structured output ở V1.
Đây là lựa chọn security có chủ đích: intent và exact tool allowlist được quyết
định trước model; câu hỏi kết hợp như trạng thái đơn + đổi trả bắt buộc gọi cả
order repository lẫn published knowledge. LLM chỉ tổng hợp trusted context.

Database tách ba credential: migration/provision, web runtime không có DDL, và
`app_agent` read-only cho product/order/warranty/retrieval. Tool tạo ticket là
side effect duy nhất và dùng service runtime có idempotency + explicit consent.

## Quyết định scale

V1 cố ý chạy một backend replica vì metric và sliding-window limiter đang nằm
trong process. Trước khi scale ngang phải chuyển hai state này sang shared store
(Redis/Prometheus-compatible metrics), chuyển upload sang object storage và chạy
retention bằng một scheduled worker duy nhất.
