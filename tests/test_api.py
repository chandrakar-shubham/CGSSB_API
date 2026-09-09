import os

os.environ["DATABASE_URL"] = "sqlite:///./test_cgssb.db"
os.environ.pop("API_KEY", None)

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_root_and_health():
    assert client.get("/").status_code == 200
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_sources():
    response = client.get("/api/v1/sources")
    assert response.status_code == 200
    assert response.json()["sources"][0]["id"] == "cg_vyapam"


def test_query_empty_database():
    response = client.get("/api/v1/query?category=all&limit=10")
    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_scrape_requires_api_key_when_configured(monkeypatch):
    from app.main import settings

    monkeypatch.setattr(settings, "api_key", "test-secret")
    response = client.post("/api/v1/scrape", json={"category": "online_application"})
    assert response.status_code == 401
    monkeypatch.setattr(settings, "api_key", None)
