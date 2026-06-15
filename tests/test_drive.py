"""Google Drive tools — mocked Drive API."""

from unittest.mock import MagicMock, patch

from tools.google_drive import read_drive_file, search_drive


def test_drive_search_mocked():
    service = MagicMock()
    service.files().list().execute.return_value = {
        "files": [{"id": "abc", "name": "Notes.txt", "mimeType": "text/plain", "modifiedTime": "2026-06-01"}],
    }
    with patch("tools.google_drive._service", return_value=service):
        result = search_drive("Notes")
    assert "Notes.txt" in result
    assert "abc" in result


def test_drive_read_mocked():
    service = MagicMock()
    service.files().get().execute.return_value = {"name": "Notes.txt", "mimeType": "text/plain"}
    service.files().get_media().execute.return_value = b"Hello drive"
    with patch("tools.google_drive._service", return_value=service):
        result = read_drive_file("abc")
    assert "Hello drive" in result
