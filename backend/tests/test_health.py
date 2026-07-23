from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


class HealthyProbe:
    async def check(self) -> None:
        return None


class UnhealthyProbe:
    async def check(self) -> None:
        raise RuntimeError("database unavailable")


def test_live_endpoint_returns_stable_contract() -> None:
    client = TestClient(create_app(readiness_probe=HealthyProbe()))

    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "vietnamese-customer-support-rag",
    }
    assert response.headers["x-request-id"]


def test_ready_endpoint_reports_dependency_failure_without_internal_details() -> None:
    client = TestClient(create_app(readiness_probe=UnhealthyProbe()))

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_NOT_READY"
    assert response.json()["error"]["message"] == "Dịch vụ chưa sẵn sàng."
    assert "database unavailable" not in response.text
    assert response.json()["request_id"] == response.headers["x-request-id"]


def test_supplied_request_id_is_preserved() -> None:
    client = TestClient(create_app(readiness_probe=HealthyProbe()))

    response = client.get(
        "/api/v1/health/live",
        headers={"x-request-id": "req-demo-123"},
    )

    assert response.headers["x-request-id"] == "req-demo-123"


def test_untrusted_request_id_is_replaced_and_security_headers_are_present() -> None:
    client = TestClient(create_app(readiness_probe=HealthyProbe()))

    response = client.get(
        "/api/v1/health/live",
        headers={"x-request-id": "x" * 200},
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"] != "x" * 200
    assert len(response.headers["x-request-id"]) == 36
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_mutating_requests_are_rate_limited_without_exposing_internals() -> None:
    settings = Settings(rate_limit_general_per_window=2)
    client = TestClient(
        create_app(
            settings=settings,
            readiness_probe=HealthyProbe(),
        )
    )
    payload = {
        "message_id": "00000000-0000-0000-0000-000000000001",
        "rating": "positive",
    }

    first = client.post("/api/v1/feedback", json=payload)
    second = client.post("/api/v1/feedback", json=payload)
    limited = client.post("/api/v1/feedback", json=payload)

    assert first.status_code == 401
    assert second.status_code == 401
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert int(limited.headers["retry-after"]) >= 1
    assert "authorization" not in limited.text.casefold()
