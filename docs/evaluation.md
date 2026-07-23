# Evaluation và release gates

## Dataset

| File | Số ca | Mục tiêu |
|---|---:|---|
| `evals/rag_eval.jsonl` | 145 | Policy retrieval, gồm 125 answerable và 20 out-of-scope |
| `evals/agent_eval.jsonl` | 244 | Intent routing và exact allowed-tool set |
| `evals/security_eval.jsonl` | 120 | Injection, cross-user, secrets và privileged actions |
| `evals/faithfulness_eval.jsonl` | 24 | Claim/citation được hỗ trợ và không được hỗ trợ |
| Tổng | 533 | Regression trước release |

Dataset là synthetic, tiếng Việt có biến thể dấu/cách nói và không chứa PII thật.
ID của từng case là duy nhất; loader từ chối dòng lỗi hoặc answerable case thiếu
expected source.

## Baseline đã đo

Kết quả từ `evals/baseline_report.json`, chạy ngày 2026-07-24:

| Metric | Kết quả | Gate |
|---|---:|---:|
| Dataset cases | 533 | ≥ 300 |
| RAG HitRate@5 | 0,976 | ≥ 0,90 |
| RAG Recall@5 | 0,976 | theo dõi |
| RAG MRR | 0,889 | theo dõi |
| Agent intent accuracy | 1,000 | ≥ 0,95 |
| Agent tool accuracy | 1,000 | ≥ 0,95 |
| Critical security bypass | 0 | = 0 |
| Supported claim acceptance | 1,000 | ≥ 0,90 |
| Citation validity accuracy | 1,000 | = 1,00 |

Tất cả gate deterministic/offline hiện pass. CI chạy lại evaluator này ở mọi
pull request/push. Đây chưa phải bằng chứng model hiện tại đạt faithfulness.

## Phương pháp

RAG baseline hiện là offline lexical retrieval trên section của bộ policy chuẩn.
Mỗi query được so với cặp `expected_title|expected_section`, lấy top 5 rồi tính
HitRate, Recall và reciprocal rank. Baseline này kiểm thử dataset/router và phát
hiện regression deterministic; nó không giả vờ là phép đo end-to-end của
embedding provider.

Agent/security evaluation chạy deterministic router và so sánh đồng thời exact
intent + exact tuple tool được phép. Critical case sai intent hoặc tool đều được
tính là bypass.

Offline claim-support evaluation dùng 12 claim được tài liệu gold hỗ trợ và 12
claim có số liệu, polarity hoặc citation sai. Nó chạy cùng `CitationVerifier`
production, đòi citation xuất hiện đúng câu, label tồn tại và từng mệnh đề được
excerpt hỗ trợ. Đây là release gate offline cho guard, không thay thế reviewer
chấm câu trả lời do provider sinh.

Chạy:

```powershell
$env:PYTHONPATH = 'backend'
backend\.venv\Scripts\python.exe -m app.evaluation.runner `
  --output evals\baseline_report.json
```

## Provider-generated release gate

Trước production, chạy model cấu hình hiện tại trên 12 câu hỏi policy gold. Mỗi
answer được kiểm lại bằng citation/excerpt production; gate yêu cầu faithfulness
≥ 0,90 và citation validity = 1,00:

```powershell
$env:OPENAI_API_KEY = '<đọc từ secret manager, không dán vào log>'
$env:PYTHONPATH = 'backend'
backend\.venv\Scripts\python.exe -m app.evaluation.provider_faithfulness `
  --output evals\provider_faithfulness_report.json
```

Workflow manual `.github/workflows/provider-faithfulness.yml` chạy cùng gate bằng
GitHub secret. Workspace ngày 2026-07-24 không có provider key, nên chưa tạo report
thật và **production release vẫn bị chặn**. Không được dùng điểm offline 1,000 để
thay thế kết quả provider-generated.

## Load smoke

`evals/load_smoke_report.json`:

- 20 request, concurrency 4;
- 20 thành công, 0 lỗi;
- p50 56 ms, p95 133 ms, max 133 ms.

Request dùng `"Xin chào"` để đi qua authentication, persistence, middleware,
stream-independent chat endpoint và cleanup conversation nhưng không gọi
LLM/embedding. Vì vậy chỉ dùng để bắt lỗi deployment/database và regression
latency cơ bản.

```powershell
backend\.venv\Scripts\python.exe scripts\smoke_load.py `
  --base-url http://127.0.0.1:8000 `
  --requests 20 --concurrency 4 `
  --output evals\load_smoke_report.json
```

## Bộ test

- Unit/API tests được đếm lại từ output CI ở từng release.
- 8 PostgreSQL/pgvector integration tests khi có test database URLs.
- Ruff toàn bộ backend/tests/scripts.
- mypy strict cho `backend/app`.
- Alembic autogenerate drift check.
- ESLint + TypeScript production build.
- Build cả backend/frontend container.

Warning còn lại là deprecation từ adapter `fastapi.testclient`/Starlette, không
phải test failure và không ảnh hưởng runtime.

## Điều kiện chặn release

Chặn nếu có một trong các điều kiện:

- test/lint/type/migration/container build fail;
- dưới 300 gold cases;
- HitRate@5 < 0,90;
- intent/tool accuracy < 0,95;
- critical bypass > 0;
- offline supported claim acceptance < 0,90 hoặc offline citation validity < 1,00;
- thiếu provider-generated report cho đúng model/prompt release, faithfulness
  < 0,90 hoặc citation validity < 1,00;
- health/readiness fail;
- production smoke có HTTP failure hoặc p95 deterministic ≥ 6 giây.

Mọi thay đổi prompt, router, tool contract, model, embedding, chunking, reranker
hoặc policy dataset đều phải chạy lại toàn bộ eval.

## Việc cần đo thêm khi có production traffic

- Reviewer sample định kỳ để đối chiếu evaluator provider-generated.
- Dense/hybrid online HitRate và no-evidence rate trên corpus đã publish.
- LLM/tool error và per-intent latency trên traffic thật. Token usage/ước tính chi
  phí đã có trong process metrics, không log prompt/PII.
- p95 theo intent, đặc biệt combined warranty + policy.
- Positive feedback và human escalation rate.
- Top no-result query đã redacted/k-anonymized.
