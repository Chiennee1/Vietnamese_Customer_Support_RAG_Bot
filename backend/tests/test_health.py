from fastapi.testclient import TestClient

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
