# Case study và portfolio evidence

## Bài toán

Một chatbot CSKH bán lẻ điện thoại phải trả policy có nguồn, nhưng giá/tồn kho,
order và warranty là dữ liệu động/cá nhân. Dùng một vector database cho tất cả sẽ
làm stale data và ownership yếu; dùng model memory sẽ tạo policy/price giả.

Giải pháp chia source of truth:

- PostgreSQL tools cho dữ liệu live và customer-specific;
- hybrid pgvector + lexical retrieval cho published policy;
- deterministic router + tool allowlist;
- backend-bound JWT identity;
- output verifier và human handoff cho quyết định nhạy cảm.

## Những quyết định quan trọng

### Không dùng raw SQL tool

Mỗi tool có typed input, hard row limit và repository riêng. Order/warranty query
luôn kèm `user_id` từ runtime, vì vậy prompt injection không thể đổi customer ID.

### Document lifecycle trước retrieval

Upload không đồng nghĩa publish. Checksum, parse, chunk, embed và DB insert phải
thành công trước `ready`; admin review mới chuyển `published`. Retrieval loại
archive, version hết hiệu lực và evidence không đủ.

### Deterministic guard trước LLM

Greeting, intent, allowed tools, severity và ticket confirmation được xử lý bằng
rule/state rõ ràng. LLM không phải nơi thực thi authorization hoặc side effect.

### Honest evaluation

464 gold cases là regression deterministic. Baseline 0,976 HitRate@5 và 1,000
tool accuracy không được quảng bá thành end-to-end model faithfulness. Load smoke
84 ms p95 là greeting không gọi model.

## Kết quả kiểm chứng

- 68 unit/API + 7 PostgreSQL integration tests.
- Cross-user order/warranty/conversation/feedback bị từ chối ở repository/API.
- 145 RAG, 199 agent, 120 security cases; 0 critical bypass.
- Alembic rollback/upgrade và schema drift check.
- Backend/frontend production container build và Docker smoke.
- Security headers, log redaction, rate limit, timeout và 30-day retention.

## Failure modes đã xử lý

- Provider timeout → safe error, không guess.
- DB down → readiness 503, không fake commerce result.
- Missing/conflicting knowledge → không xác nhận, human review.
- Unsupported refund/replacement/warranty promise → output verifier chặn.
- Bad document → archive/republish version trước.
- Repeated/safety/legal complaint → explicit human reason/action.

## Trade-off V1

- In-memory metric/rate-limit làm V1 chỉ một backend replica.
- Persistent upload volume phù hợp portfolio/one-replica nhưng object storage tốt
  hơn cho scale/zero-downtime.
- SSE hiện stream answer đã được guard/persist, không token-stream trực tiếp từ
  provider; latency đầu tiên cao hơn nhưng không stream nội dung chưa verify.
- Offline lexical eval deterministic và rẻ, nhưng cần online dense/hybrid +
  reviewer faithfulness khi production corpus ổn định.

## Hướng cải tiến

1. Object storage + background queue cho ingestion.
2. Redis/shared limiter và Prometheus/OpenTelemetry.
3. JWT rotation/revocation, SSO và immutable audit log.
4. End-to-end citation precision/faithfulness evaluation.
5. Reranker benchmark và per-intent latency/cost.
6. Ticket integration với hệ thống support thật sau approval/idempotency design.

## CV-ready bullets

> Built a production-oriented Vietnamese customer-support assistant with FastAPI,
> PostgreSQL/pgvector and React, combining citation-grounded policy retrieval with
> authorization-scoped product, order, inventory and warranty tools.

> Designed backend-enforced source-of-truth and ownership boundaries, deterministic
> tool routing, prompt-injection defenses and human escalation; validated them on
> 464 synthetic RAG/agent/security cases with zero critical routing bypasses.

> Implemented idempotent document ingestion, hybrid retrieval, validated citations,
> Alembic migrations, structured privacy-safe observability, Docker/Railway
> deployment configuration and CI release gates.

Chỉ dùng các bullet này kèm link commit/report; không nói “live production” cho
tới khi có URL và production smoke thực tế.

## Evidence map

| Evidence | Vị trí |
|---|---|
| Architecture | `docs/architecture.md` |
| Evaluation report | `evals/baseline_report.json` |
| Security tests | `backend/tests/test_output_verifier.py`, `security_eval.jsonl` |
| Ownership integration | `backend/tests/integration/` |
| Docker | `docker-compose.yml`, hai Dockerfile |
| CI | `.github/workflows/ci.yml` |
| Railway | hai `railway.toml`, `docs/deployment-railway.md` |
| Operations/backup/privacy | `docs/` |

Demo storyboard chi tiết nằm ở [demo-script.md](demo-script.md).
