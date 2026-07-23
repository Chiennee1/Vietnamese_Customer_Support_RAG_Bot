# Triển khai Railway

Tài liệu này dùng kiến trúc ba service: `Postgres` (image/template có pgvector),
`backend` và `frontend`. Repository là isolated monorepo; mỗi application có
Dockerfile và `railway.toml` riêng.

> Trạng thái workspace ngày 2026-07-23: cấu hình đã được build/test local nhưng
> chưa có Railway CLI, token, project hoặc Git remote nên chưa thể tạo live URL
> từ workspace này. Không được coi “deployment-ready” là “đã deploy”.

## 1. Điều kiện trước khi deploy

- Code đã push lên GitHub và CI của commit mục tiêu xanh.
- Có Railway project/environment production.
- Có OpenAI API key được phê duyệt và ngân sách/limit.
- Có hai secret ngẫu nhiên độc lập cho `APP_SECRET`, `JWT_SECRET`.
- Có domain dự kiến cho backend/frontend.
- Có lịch backup và owner xử lý incident.

Không copy `.env` local lên Railway và không dùng mật khẩu demo ở production.

## 2. Tạo database pgvector

Tạo database từ pgvector template/marketplace, đặt service name là `Postgres`.
Default PostgreSQL template của Railway không cam kết bundle extension; migration
đầu tiên có `CREATE EXTENSION vector` nên phải chọn image/template có pgvector.

Chờ database healthy. Backend sẽ dùng reference variable:

```text
DATABASE_URL=${{Postgres.DATABASE_URL}}
```

App tự chuẩn hoá `postgres://`/`postgresql://` thành SQLAlchemy asyncpg URL. Không
dùng public TCP URL giữa hai service trong cùng project.

Bật Railway volume backups cho database: daily + weekly + monthly. Với dữ liệu
quan trọng, bổ sung logical `pg_dump` ngoài project theo
[backup-restore.md](backup-restore.md).

## 3. Tạo backend service

1. Tạo empty service `backend`, kết nối GitHub repository/branch.
2. Settings → Root Directory: `/backend`.
3. Config file path: `/backend/railway.toml`.
4. Generate Domain.
5. Gắn volume tên `uploads`, mount `/app/uploads`.

Đặt variables:

```text
APP_ENV=production
APP_SECRET=<sealed-random-secret>
JWT_SECRET=<sealed-random-secret-different-from-app-secret>
DATABASE_URL=${{Postgres.DATABASE_URL}}
OPENAI_API_KEY=<sealed-provider-key>
LLM_PROVIDER=openai
LLM_MODEL=gpt-5-mini
LLM_MAX_OUTPUT_TOKENS=700
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
UPLOAD_DIR=/app/uploads
CORS_ORIGINS=https://<frontend-domain>
RAILWAY_RUN_UID=0
CONVERSATION_RETENTION_DAYS=30
```

Các timeout, RAG, rate limit và upload limit còn lại có default an toàn trong
`.env.example`; chỉ override khi đã đo. `RAILWAY_RUN_UID=0` cho phép entrypoint
chown volume Railway rồi lập tức hạ process xuống UID/GID 10001 bằng `setpriv`.
Kiểm tra log startup để chắc process app không chạy root.

`backend/railway.toml` đảm nhiệm:

- Dockerfile build;
- Alembic `upgrade head` trong pre-deploy container;
- readiness `/api/v1/health/ready`;
- timeout 300 giây;
- restart on failure, tối đa 5 lần;
- 20 giây draining.

Không seed synthetic trong production. Nếu tạo environment portfolio demo riêng,
chỉ chạy `uv run --no-sync python -m app.db.seed` một lần và dán nhãn environment
là synthetic.

## 4. Tạo frontend service

1. Tạo service `frontend`, kết nối cùng repo/branch.
2. Root Directory: `/frontend`.
3. Config file path: `/frontend/railway.toml`.
4. Đặt build variable:

```text
VITE_API_BASE_URL=https://<backend-domain>/api/v1
```

5. Deploy, generate frontend domain.
6. Cập nhật backend `CORS_ORIGINS` đúng origin frontend, không có slash cuối.
7. Redeploy backend và frontend nếu domain/API variable thay đổi.

Nginx template lắng nghe `$PORT` do Railway inject và trả security headers/CSP.
Không đặt secret trong `VITE_*`; giá trị này xuất hiện công khai trong JS bundle.

## 5. Publish knowledge base

Sau deploy:

1. Tạo admin theo quy trình quản trị được phê duyệt. Dataset seed chỉ dành demo.
2. Đăng nhập `/admin/knowledge`.
3. Upload từng file chính sách đã review từ `data/knowledge`.
4. Chờ `ready`, kiểm tra title/version/effective dates.
5. Publish một version hiệu lực cho mỗi policy category.
6. Chạy policy smoke test và kiểm tra citation đúng document/section.

Không publish hàng loạt khi chưa review extraction. Version cũ phải archive, không
xoá lịch sử.

## 6. Verification sau deploy

PowerShell:

```powershell
$backend = 'https://<backend-domain>'
$frontend = 'https://<frontend-domain>'

Invoke-RestMethod "$backend/api/v1/health/live"
Invoke-RestMethod "$backend/api/v1/health/ready"
Invoke-WebRequest $frontend -Method Head
```

Smoke có xác thực:

```powershell
backend\.venv\Scripts\python.exe scripts\smoke_load.py `
  --base-url $backend `
  --email '<synthetic-demo-user-if-demo-environment>' `
  --password '<read-from-secret-manager>' `
  --requests 20 --concurrency 4
```

Kiểm tra thủ công:

- login/logout và auth expiry;
- lời chào không gọi tool;
- tìm sản phẩm trả price/stock hiện tại;
- customer A không đọc được order/warranty customer B;
- policy answer có citation;
- prompt injection không bypass;
- complaint chỉ tạo ticket sau xác nhận;
- admin upload/publish/archive;
- logs không có token/email/body;
- `/docs` và `/openapi.json` trả 404 ở production.

## 7. Rollout và rollback

Thứ tự release:

1. CI xanh và review migration.
2. Tạo backup; ghi lại deployment ID và DB revision.
3. Pre-deploy migration.
4. Backend health/readiness.
5. Frontend deploy.
6. Smoke test.
7. Theo dõi error/p95/no-evidence trong 15–30 phút.

Rollback code bằng Railway deployment rollback về image trước. Chỉ downgrade DB
khi migration đã được chứng minh backward-compatible và runbook của migration cho
phép; mặc định ưu tiên roll-forward. Không restore backup trực tiếp đè production
trước khi xác minh trên environment tách biệt.

## 8. Production caveats

- Một backend replica ở V1 vì limiter/metrics process-local.
- Service có volume sẽ có một khoảng downtime nhỏ khi redeploy theo mô hình
  volume attach của Railway.
- Railway healthcheck là deployment gate, không phải continuous monitoring; cần
  external uptime monitor gọi `/health/ready`.
- Pre-deploy container không mount upload volume; migration không được phụ thuộc
  filesystem.

Tham khảo Railway chính thức:

- <https://docs.railway.com/deployments/monorepo>
- <https://docs.railway.com/config-as-code/reference>
- <https://docs.railway.com/deployments/pre-deploy-command>
- <https://docs.railway.com/deployments/healthchecks>
- <https://docs.railway.com/volumes>
- <https://docs.railway.com/volumes/backups>
- <https://docs.railway.com/databases/postgresql>
