from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_chat_roundtrip():
    resp = client.post("/chat", json={"message": "Hello, remember that I like tea."})
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"]
    assert body["reply"]


def test_beliefs_endpoint():
    resp = client.get("/memory/beliefs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_audit_endpoint():
    resp = client.get("/memory/audit")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_metrics_endpoint():
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert "table_row_counts" in body
    assert "episodic_memory" in body["table_row_counts"]
    assert "active_beliefs" in body
    assert "audit_actions" in body


def test_seed_demo_endpoint():
    resp = client.post("/demo/seed", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"]
    assert body["seeded_turns"] > 0

    metrics = client.get("/metrics").json()
    assert metrics["table_row_counts"]["episodic_memory"] > 0


def test_api_token_gate(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "_API_TOKEN", "secret123")
    try:
        resp = client.get("/metrics")
        assert resp.status_code == 401

        resp = client.get("/health")
        assert resp.status_code == 200, "health check must stay open even with a token set"

        resp = client.get("/metrics", headers={"X-API-Token": "secret123"})
        assert resp.status_code == 200
    finally:
        monkeypatch.setattr(main_module, "_API_TOKEN", None)
