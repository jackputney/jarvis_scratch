"""Dashboard endpoint smoke tests — 200 + valid JSON, no real LLM calls."""

import pytest

from dashboard.app import create_app


@pytest.fixture
def client(temp_env):
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture(autouse=True)
def _reset_interrupt():
    """Clear any global interrupt the orchestrator/cancel path may leave set."""
    yield
    import sys

    pipeline = sys.modules.get("pipeline")
    if pipeline is not None:
        pipeline._clear_interrupt()


def test_index_serves(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Jarvis" in r.data


@pytest.mark.parametrize("url", ["/api/state", "/api/config", "/api/variables", "/api/notes"])
def test_get_endpoints_return_json_200(client, url):
    r = client.get(url)
    assert r.status_code == 200
    assert r.is_json
    r.get_json()  # raises if not valid JSON


def test_state_shape(client):
    data = client.get("/api/state").get_json()
    assert {"pipeline_state", "muted", "uptime_seconds", "models", "spend", "conversations", "pending_confirm"} <= data.keys()
    assert {"today", "week", "month", "daily_budget", "monthly_budget", "daily_pct"} <= data["spend"].keys()
    assert data["pending_confirm"] is None


def test_variable_crud(client):
    assert client.post("/api/variables", json={"key": "home_city", "value": "London"}).get_json()["ok"]
    assert client.get("/api/variables").get_json()["home_city"] == "London"
    assert client.delete("/api/variables/home_city").get_json()["ok"] is True


def test_note_crud(client):
    assert client.post("/api/notes", json={"title": "Groceries", "content": "milk"}).get_json()["ok"]
    titles = client.get("/api/notes").get_json()["notes"]
    assert "Groceries" in titles
    body = client.get("/api/notes/Groceries").get_json()
    assert "milk" in body["content"]
    assert client.delete("/api/notes/Groceries").get_json()["ok"] is True


def test_config_post_updates(client):
    r = client.post("/api/config", json={"daily_budget_usd": 7.5})
    assert r.status_code == 200
    assert r.get_json()["config"]["daily_budget_usd"] == 7.5


def test_message_requires_text(client):
    r = client.post("/api/message", json={})
    assert r.status_code == 400


def test_interrupt_endpoint(client):
    r = client.post("/api/interrupt")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


def test_confirm_respond_requires_id(client):
    r = client.post("/api/confirm/respond", json={"allow": True})
    assert r.status_code == 400


def test_confirm_respond_404_when_no_pending(client):
    r = client.post("/api/confirm/respond", json={"id": "missing", "allow": True})
    assert r.status_code == 404


def test_message_busy_returns_409(client, temp_env, monkeypatch):
    import pipeline

    monkeypatch.setattr(
        pipeline,
        "process_query",
        lambda text, cfg, on_state=None: {
            "reply": pipeline.BUSY_MESSAGE,
            "busy": True,
            "model": "(busy)",
            "latency_ms": 0,
            "cost": 0.0,
        },
    )
    r = client.post("/api/message", json={"text": "hi"})
    assert r.status_code == 409
    assert r.get_json()["busy"] is True


def test_message_happy_path_returns_reply(client, temp_env, monkeypatch):
    import pipeline

    monkeypatch.setattr(
        pipeline,
        "process_query",
        lambda text, cfg, on_state=None: {
            "reply": "hello back",
            "busy": False,
            "model": "m",
            "latency_ms": 12,
            "cost": 0.001,
        },
    )
    r = client.post("/api/message", json={"text": "hi"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["reply"] == "hello back"
    assert body["model"] == "m"
