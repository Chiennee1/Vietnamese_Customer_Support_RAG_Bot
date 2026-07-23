from collections import deque

from app.core.metrics import MetricsRegistry
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.redaction import redact_text, redact_value


def test_metrics_snapshot_reports_percentiles_and_business_rates() -> None:
    metrics = MetricsRegistry()
    for latency in (10, 20, 30, 40, 100):
        metrics.record_request(
            route="/api/v1/chat",
            status_code=200,
            latency_ms=latency,
        )
    metrics.record_chat(
        intent="order_status",
        status="success",
        latency_ms=80,
        tool_names=("get_order_status",),
    )
    metrics.record_chat(
        intent="complaint",
        status="success",
        latency_ms=120,
        requires_human=True,
        ticket_created=True,
    )
    metrics.record_feedback("positive")
    metrics.record_feedback("negative")
    metrics.record_rag(
        insufficient=True,
        conflict=False,
        retrieved_count=0,
        latency_ms=25,
    )

    snapshot = metrics.snapshot()
    api = snapshot["api"]
    chat = snapshot["chat"]
    feedback = snapshot["feedback"]

    assert isinstance(api, dict)
    assert api["latency"]["/api/v1/chat"]["p95_ms"] == 100
    assert chat["human_escalation_rate"] == 0.5
    assert chat["tickets_created"] == 1
    assert chat["tools"]["get_order_status"] == 1
    assert feedback["positive_rate"] == 0.5
    assert snapshot["rag"]["no_result"] == 1


def test_empty_latency_summary_is_stable() -> None:
    summary = MetricsRegistry._latency(deque())

    assert summary.count == 0
    assert summary.p95_ms == 0


def test_log_redaction_removes_secrets_and_common_pii_recursively() -> None:
    text = (
        "Email an.nguyen@example.test, số 0912 345 678, "
        "Bearer eyJhbGciOiJIUzI1NiJ9.demo.signature, sk-demo-secret-1234 "
        "và thẻ 4111 1111 1111 1111."
    )
    redacted = redact_text(text)
    payload = redact_value(
        {
            "authorization": "Bearer secret-value",
            "nested": {"email": "an.nguyen@example.test"},
            "message": "nội dung khách hàng",
        }
    )

    assert "an.nguyen@example.test" not in redacted
    assert "0912 345 678" not in redacted
    assert "eyJhbGci" not in redacted
    assert "sk-demo" not in redacted
    assert "4111 1111" not in redacted
    assert payload["authorization"] == "[REDACTED]"
    assert payload["message"] == "[REDACTED]"
    assert payload["nested"]["email"] == "[EMAIL_REDACTED]"


def test_rate_limiter_is_bounded_and_expires_old_windows() -> None:
    limiter = SlidingWindowRateLimiter(
        {"general": 2},
        window_seconds=10,
        max_buckets=2,
    )

    assert limiter.check(scope="general", key="a", now=0).allowed
    assert limiter.check(scope="general", key="a", now=1).allowed
    assert not limiter.check(scope="general", key="a", now=2).allowed
    limiter.check(scope="general", key="b", now=2)
    limiter.check(scope="general", key="c", now=3)

    assert len(limiter.events) == 2
    assert limiter.check(scope="general", key="a", now=12).allowed
