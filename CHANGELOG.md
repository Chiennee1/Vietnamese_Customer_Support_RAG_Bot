# Changelog

## 1.0.0 — 2026-07-23

Production-portfolio release:

- FastAPI/PostgreSQL/pgvector foundation, JWT auth and synthetic commerce data.
- Secure Markdown/PDF ingestion with versioned publish/archive lifecycle.
- Hybrid retrieval, reranking, validated citations and no-evidence fallback.
- Authorization-scoped product, order, warranty and support-ticket tools.
- Guarded Vietnamese support orchestration, complaint severity and human handoff.
- Persistent chat, SSE, feedback and React admin/customer workspace.
- Structured redacted logs, process metrics, rate limit, timeout and retention.
- 464 deterministic RAG/agent/security cases and local load smoke.
- Docker Compose, Railway monorepo configuration, GitHub Actions CI, backup,
  security, privacy, operations and portfolio documentation.

Known constraints:

- one backend replica until rate limit/metrics use a shared backend;
- upload originals use a persistent volume;
- Railway live deployment and recorded demo require external account/browser
  access not present in this workspace.
