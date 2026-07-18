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
