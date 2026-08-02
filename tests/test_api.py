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


def test_belief_timeline_endpoint():
    resp = client.get("/memory/beliefs/timeline")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_why_endpoint_404_for_unknown_belief():
    import uuid

    resp = client.get(f"/memory/beliefs/{uuid.uuid4()}/why")
    assert resp.status_code == 404


def test_why_endpoint_400_for_malformed_id():
    resp = client.get("/memory/beliefs/not-a-uuid/why")
    assert resp.status_code == 400


def test_why_endpoint_returns_provenance_for_real_belief():
    """Create a belief through the real API (chat), find it, and confirm
    its /why provenance response has the documented shape."""
    import uuid

    from anamnesis.memory import Anamnesis

    mem = Anamnesis()
    ep = mem.remember(uuid.uuid4(), "user", "user's favorite color is blue")
    belief = mem.detect_and_resolve_contradiction(
        "user's favorite color is blue", source_episode_ids=[ep]
    )
    resp = client.get(f"/memory/beliefs/{belief.id}/why")
    assert resp.status_code == 200
    body = resp.json()
    assert body["belief"]["belief"] == "user's favorite color is blue"
    assert isinstance(body["evidence"], list)
    assert body["evidence"][0]["id"] == str(ep)


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
