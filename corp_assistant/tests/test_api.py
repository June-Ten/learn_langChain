import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MYSQL_DATABASE", "langchain_test")
    monkeypatch.setenv("CORP_API_KEYS", "test-key")
    monkeypatch.setenv("CORP_RATE_LIMIT", "0")
    from corp_assistant.auth import reset_rate_limit
    from corp_assistant.main import create_app
    from corp_assistant import store

    reset_rate_limit()
    create_app()
    with store.get_conn() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for name in (
            "messages",
            "conversations",
            "tickets",
            "audit_logs",
            "knowledge_notes",
            "employees",
        ):
            conn.execute(text(f"DELETE FROM {name}"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    store.seed()
    return TestClient(create_app())


def headers(user="E004"):
    return {"X-API-Key": "test-key", "X-User-Id": user}


def test_health_is_public(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/ready").status_code == 200


def test_auth_required(client):
    assert client.get("/api/v1/me").status_code == 401
    denied = client.get("/api/v1/me", headers={"X-API-Key": "nope", "X-User-Id": "E004"})
    assert denied.status_code == 401
    missing_user = client.get("/api/v1/me", headers={"X-API-Key": "test-key"})
    assert missing_user.status_code == 401


def test_me_and_directory(client):
    me = client.get("/api/v1/me", headers=headers()).json()
    assert me["name"] == "赵敏"
    found = client.get("/api/v1/employees", headers=headers(), params={"q": "王芳"}).json()
    assert found["total"] == 1
    assert found["items"][0]["id"] == "E002"
    departments = client.get("/api/v1/departments", headers=headers()).json()
    assert "财务部" in departments


def test_ticket_visibility_and_audit(client):
    created = client.post(
        "/api/v1/tickets",
        headers=headers("E003"),
        json={
            "title": "报销差旅",
            "description": "上海出差住宿",
            "category": "finance",
            "priority": "low",
        },
    )
    assert created.status_code == 200
    ticket_id = created.json()["id"]

    own = client.get("/api/v1/tickets", headers=headers("E003")).json()
    assert any(item["id"] == ticket_id for item in own["items"])

    other = client.get("/api/v1/tickets", headers=headers("E004")).json()
    assert all(item["id"] != ticket_id for item in other["items"])

    hr = client.get("/api/v1/tickets", headers=headers("E002")).json()
    assert all(item["id"] != ticket_id for item in hr["items"])

    finance = client.get(f"/api/v1/tickets/{ticket_id}", headers=headers("E005"))
    assert finance.status_code == 200

    forbidden = client.patch(
        f"/api/v1/tickets/{ticket_id}",
        headers=headers("E003"),
        json={"status": "resolved"},
    )
    assert forbidden.status_code == 403

    updated = client.patch(
        f"/api/v1/tickets/{ticket_id}",
        headers=headers("E005"),
        json={"status": "in_progress"},
    )
    assert updated.json()["status"] == "in_progress"

    staff_audit = client.get("/api/v1/audit", headers=headers("E004"))
    assert staff_audit.status_code == 403
    audit = client.get("/api/v1/audit", headers=headers("E001")).json()
    actions = {item["action"] for item in audit["items"]}
    assert "ticket.create" in actions
    assert "ticket.update" in actions


def test_knowledge_search_and_note(client):
    hits = client.get("/api/v1/knowledge/search", headers=headers(), params={"q": "年假"}).json()
    assert hits["items"]
    assert any("5 天" in item["content"] for item in hits["items"])

    denied = client.post(
        "/api/v1/knowledge/notes",
        headers=headers("E004"),
        json={"title": "临时通知", "body": "周五下午演练 VPN。"},
    )
    assert denied.status_code == 403
    created = client.post(
        "/api/v1/knowledge/notes",
        headers=headers("E001"),
        json={"title": "临时通知", "body": "周五下午演练 VPN。"},
    )
    assert created.status_code == 200
    found = client.get(
        "/api/v1/knowledge/search",
        headers=headers(),
        params={"q": "演练"},
    ).json()
    assert any(item["source"].startswith("note:") for item in found["items"])


def test_metrics_admin_only(client):
    assert client.get("/api/v1/metrics", headers=headers("E004")).status_code == 403
    metrics = client.get("/api/v1/metrics", headers=headers("E001")).json()
    assert metrics["employees"] == 5
    assert metrics["knowledge_chunks"] >= 4


def test_validation_and_rate_limit(client, monkeypatch):
    bad = client.post(
        "/api/v1/tickets",
        headers=headers(),
        json={"title": "x", "description": "y", "category": "nope"},
    )
    assert bad.status_code == 422

    from corp_assistant.auth import reset_rate_limit

    reset_rate_limit()
    monkeypatch.setenv("CORP_RATE_LIMIT", "2")
    assert client.get("/api/v1/me", headers=headers()).status_code == 200
    assert client.get("/api/v1/me", headers=headers()).status_code == 200
    assert client.get("/api/v1/me", headers=headers()).status_code == 429
