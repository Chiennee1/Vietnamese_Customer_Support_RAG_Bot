# Vietnamese Customer Support RAG Bot

Trợ lý CSKH tiếng Việt production-oriented cho hệ thống bán lẻ điện thoại. Hệ
thống kết hợp knowledge base có trích dẫn với dữ liệu giao dịch PostgreSQL được
phân quyền, thay vì dùng trí nhớ của mô hình cho giá, tồn kho, đơn hàng, bảo hành
hoặc chính sách riêng của cửa hàng.

## Trạng thái

- Backend FastAPI, PostgreSQL 16 + pgvector, SQLAlchemy async và Alembic.
- Frontend React/Vite với đăng nhập, chat streaming, citation, feedback và trang
  quản trị knowledge base/hàng đợi vận hành.
- 500 khách hàng synthetic, 100 sản phẩm, 300 SKU, 1.000 đơn hàng, 600 bảo hành
  và 200 ticket.
- 509 gold cases; toàn bộ deterministic release gate hiện đạt.
- Docker Compose local và cấu hình Railway cho monorepo đã sẵn sàng.

```mermaid
flowchart LR
    U[Khách hàng] --> F[React frontend]
    A[Admin / Support] --> F
    F --> API[FastAPI]
    API --> AUTH[JWT + runtime identity]
    API --> ROUTER[Deterministic intent router]
    ROUTER --> ORCH[Guarded orchestrator]
    ORCH --> KB[Hybrid RAG + citations]
    ORCH --> TOOLS[Constrained business tools]
    KB --> DB[(PostgreSQL + pgvector)]
    TOOLS --> DB
    API --> OBS[Structured logs + metrics]
```

## Source of truth

| Loại thông tin | Nguồn bắt buộc |
|---|---|
| Giá và tồn kho hiện tại | Business tool đọc PostgreSQL |
| Đơn hàng của khách | Order tool với user ID từ JWT |
| Bảo hành cụ thể | Warranty tool với user ID từ JWT |
| Chính sách, điều kiện, FAQ | Tài liệu đã publish qua hybrid RAG |
| Trường hợp vừa có trạng thái vừa có điều kiện | SQL tool + RAG |

Không có raw SQL tool. Model không được tự chọn hoặc thay đổi định danh phân
quyền. Nội dung upload/retrieve luôn được coi là dữ liệu, không phải chỉ thị.
Các tool đọc dùng PostgreSQL role `app_agent` chỉ có SELECT; migration, web
workflow và agent không dùng chung credential.

## Chạy local

Yêu cầu: Docker Desktop và Docker Compose.

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
```

Mở:

- Frontend: `http://localhost:5173`
- API docs ở môi trường development: `http://localhost:8000/docs`
- Readiness: `http://localhost:8000/api/v1/health/ready`

Tài khoản synthetic:

| Vai trò | Email | Mật khẩu demo |
|---|---|---|
| Admin | `customer0000@example.test` | `Demo-customer-2026` |
| Support | `customer0001@example.test` | `Demo-customer-2026` |
| Customer | `customer0006@example.test` | `Demo-customer-2026` |

Customer trên sở hữu đơn `DH2026000001` và serial `SN2600000001`. Chỉ sử dụng
các tài khoản này với dữ liệu synthetic, không dùng mật khẩu demo ở production.

Để có policy answer, đăng nhập admin, mở `/admin/knowledge`, upload các file
trong `data/knowledge/`, chờ trạng thái `ready`, kiểm tra nội dung rồi publish.

## Kiểm thử

Backend:

```powershell
$env:TEST_DATABASE_URL = 'postgresql+asyncpg://app_runtime:local-runtime-password@127.0.0.1:5432/support_rag'
$env:TEST_AGENT_DATABASE_URL = 'postgresql+asyncpg://app_agent:local-agent-password@127.0.0.1:5432/support_rag'
Set-Location backend
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check app tests ..\scripts
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m alembic check
```

Frontend và release evaluation:

```powershell
Set-Location frontend
npm run lint
npm run build
Set-Location ..
$env:PYTHONPATH = 'backend'
backend\.venv\Scripts\python.exe -m app.evaluation.runner
```

Baseline ngày 2026-07-23:

| Gate | Kết quả |
|---|---:|
| Dataset | 509 cases |
| Offline lexical RAG HitRate@5 / Recall@5 | 0,976 / 0,976 |
| Offline lexical RAG MRR | 0,889 |
| Agent intent / tool accuracy | 1,000 / 1,000 |
| Security critical bypass | 0 |
| Local HTTP smoke, 20 request / concurrency 4 | 100% success, p95 136 ms |

Load smoke chỉ dùng lời chào deterministic, không đại diện latency hoặc chi phí
của request có LLM/embedding. Xem phương pháp và giới hạn trong
[docs/evaluation.md](docs/evaluation.md).

## Tài liệu

- [Kiến trúc và request flow](docs/architecture.md)
- [API contract](docs/api.md)
- [Threat model và security controls](docs/security.md)
- [Evaluation và release gates](docs/evaluation.md)
- [Triển khai Railway](docs/deployment-railway.md)
- [Runbook vận hành và incident](docs/operations-runbook.md)
- [Backup và restore](docs/backup-restore.md)
- [Privacy và retention](docs/privacy-retention.md)
- [Case study, demo script và CV evidence](docs/case-study.md)

## CI/CD

`.github/workflows/ci.yml` chạy ba job độc lập:

1. Backend lint, mypy strict, migration drift, unit/integration PostgreSQL và
   release eval.
2. Frontend lint và production build.
3. Build cả hai production container.

Mọi deployment phải chờ CI xanh. Dependabot tạo PR định kỳ; không tự nâng
dependency production mà không chạy regression/eval.

## Giới hạn V1

- Metric và rate limit là process-local; production V1 chạy một backend replica.
- Upload gốc dùng persistent volume. Khi scale nhiều replica cần chuyển sang
  object storage và metric/rate-limit shared.
- Không tự động phê duyệt hoàn tiền, đổi máy, giảm giá hoặc bảo hành.
- Không có thanh toán, sửa đơn hoặc cập nhật tồn kho bằng AI.
- API docs bị tắt khi `APP_ENV=production`.

Toàn bộ dữ liệu demo là synthetic và không đại diện cho khách hàng hoặc sản phẩm
thương mại thật.
