"""Dashboard contacts API and google_contacts helpers."""

from unittest.mock import patch

import pytest

from dashboard.app import create_app


@pytest.fixture
def client(temp_env):
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_api_contacts_returns_list(client):
    with patch(
        "tools.google_contacts.list_contacts_full",
        return_value=[{"name": "John Doe", "email": "john@example.com", "initials": "JD"}],
    ):
        resp = client.get("/api/contacts")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "contacts" in data
    assert len(data["contacts"]) == 1
    assert data["contacts"][0]["name"] == "John Doe"


def test_api_contacts_handles_error(client):
    with patch("tools.google_contacts.list_contacts_full", side_effect=Exception("No auth")):
        resp = client.get("/api/contacts")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["contacts"] == []
    assert "error" in data


def test_list_contacts_full_skips_nameless():
    people = [
        {
            "names": [{"displayName": "Jane Doe", "givenName": "Jane", "familyName": "Doe"}],
            "emailAddresses": [{"value": "jane@example.com"}],
            "phoneNumbers": [],
            "organizations": [],
            "photos": [],
        },
        {
            "names": [],
            "emailAddresses": [{"value": "ghost@example.com"}],
        },
    ]
    with patch("tools.google_contacts._all_contacts", return_value=people):
        from tools.google_contacts import list_contacts_full

        contacts = list_contacts_full(count=10)
    assert len(contacts) == 1
    assert contacts[0]["name"] == "Jane Doe"


def test_index_includes_contacts_nav(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"data-view=\"contacts\"" in r.data
    assert b"Contacts</span>" in r.data
    assert b"/api/contacts" not in r.data  # API is JS-fetched, not inline


def test_get_initials():
    from tools.google_contacts import _get_initials

    assert _get_initials("John Doe") == "JD"
    assert _get_initials("Madonna") == "M"
    assert _get_initials("Mary Jane Watson") == "MW"
    assert _get_initials("") == "?"
