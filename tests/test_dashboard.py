"""Dashboard endpoint smoke tests — 200 + valid JSON, no real LLM calls."""

import pytest

from dashboard.app import create_app


@pytest.fixture
def client(temp_env):
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


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
    assert {"pipeline_state", "muted", "uptime_seconds", "models", "spend", "conversations"} <= data.keys()
    assert {"today", "week", "month", "daily_budget", "monthly_budget", "daily_pct"} <= data["spend"].keys()


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
