from fastapi.testclient import TestClient

from app.auth import create_access_token
from app.main import app


client = TestClient(app)


def test_health_reports_database_readiness(monkeypatch):
    monkeypatch.setattr("app.main._database_ready", lambda: True)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "checks": {"database": "up"}}


def test_health_returns_503_when_database_is_down(monkeypatch):
    monkeypatch.setattr("app.main._database_ready", lambda: False)
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "down"


def test_monitoring_endpoints_require_login():
    assert client.get("/metrics").status_code == 401
    assert client.get("/admin/stats").status_code == 401


def test_monitoring_endpoints_accept_valid_access_token():
    token = create_access_token(42, "monitor")
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/metrics", headers=headers).status_code == 200
    assert client.get("/admin/stats", headers=headers).status_code == 200
