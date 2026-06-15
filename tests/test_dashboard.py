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
    assert b"Hub" in r.data
    assert b"hub.js" in r.data


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
        lambda text, cfg, on_state=None, speak=False: {
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


def test_tools_list_includes_tiers(client):
    tools = client.get("/api/tools").get_json()["tools"]
    names = {t["name"] for t in tools}
    assert {"send_email", "web_search", "get_variable"} <= names
    by_name = {t["name"]: t for t in tools}
    assert by_name["send_email"]["tier"] == "high"
    assert by_name["web_search"]["tier"] == "read"
    assert by_name["set_variable"]["tier"] == "write"
    assert "input_schema" in by_name["send_email"]


def test_tool_run_set_then_get(client, temp_env):
    r = client.post("/api/tools/run", json={"name": "set_variable", "inputs": {"key": "city", "value": "London"}})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    r2 = client.post("/api/tools/run", json={"name": "get_variable", "inputs": {"key": "city"}})
    assert "London" in r2.get_json()["result"]


def test_tool_run_unknown_returns_404(client):
    r = client.post("/api/tools/run", json={"name": "does_not_exist", "inputs": {}})
    assert r.status_code == 404
    assert r.get_json()["ok"] is False


def test_tool_run_requires_name(client):
    r = client.post("/api/tools/run", json={"inputs": {}})
    assert r.status_code == 400


def test_sse_replays_initial_state():
    from dashboard.app import _initial_sse_payloads

    payloads = _initial_sse_payloads()
    assert payloads
    joined = " ".join(payloads)
    assert "pipeline.state" in joined or '"type": "state"' in joined


def test_api_metrics_shape(client):
    data = client.get("/api/metrics").get_json()
    assert {"uptime_seconds", "uptime_display", "queries_today", "tools_today"} <= data.keys()


def test_message_happy_path_returns_reply(client, temp_env, monkeypatch):
    import pipeline

    monkeypatch.setattr(
        pipeline,
        "process_query",
        lambda text, cfg, on_state=None, speak=False: {
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
