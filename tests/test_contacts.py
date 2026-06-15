"""Google Contacts tools — mocked People API."""

from unittest.mock import MagicMock, patch

from tools.google_contacts import list_contacts, search_contacts


def _mock_people():
    return [
        {
            "names": [{"displayName": "Oliver Smith"}],
            "emailAddresses": [{"value": "oliver@example.com"}],
            "phoneNumbers": [{"value": "+1 555 0100"}],
        },
        {
            "names": [{"displayName": "Jane Doe"}],
            "emailAddresses": [{"value": "jane@example.com"}],
            "phoneNumbers": [],
        },
    ]


def test_contacts_search_mocked():
    with patch("tools.google_contacts._all_contacts", return_value=_mock_people()):
        result = search_contacts("Oliver")
    assert "Oliver Smith" in result
    assert "oliver@example.com" in result


def test_contacts_list_mocked():
    with patch("tools.google_contacts._all_contacts", return_value=_mock_people()):
        result = list_contacts(2)
    assert "Oliver Smith" in result
    assert "Jane Doe" in result
