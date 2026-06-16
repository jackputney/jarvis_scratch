"""Download tool — mocked HTTP, isolated Downloads dir."""

from unittest.mock import MagicMock, patch

import tools.download as dl
from tools.download import download_file
from tools.registry import CONFIRM_REQUIRED_TOOLS, READ_ONLY_TOOLS


def _mock_get(chunks, headers=None, status=200):
    """Build a context-manager mock matching `requests.get(..., stream=True)`."""
    resp = MagicMock()
    resp.headers = headers or {}
    resp.status_code = status
    resp.raise_for_status.return_value = None
    resp.iter_content.return_value = iter(chunks)
    cm = MagicMock()
    cm.__enter__.return_value = resp
    cm.__exit__.return_value = False
    return cm


def test_download_rejects_non_http():
    assert "refused" in download_file("ftp://example.com/x").lower()
    assert "refused" in download_file("file:///etc/passwd").lower()
    assert "refused" in download_file("not a url").lower()


def test_download_saves_file(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "_downloads_dir", lambda: tmp_path)
    cm = _mock_get([b"hello ", b"world"])
    with patch("requests.get", return_value=cm):
        result = download_file("https://example.com/greeting.txt")
    saved = tmp_path / "greeting.txt"
    assert saved.exists()
    assert saved.read_bytes() == b"hello world"
    assert "greeting.txt" in result


def test_download_infers_name_from_content_disposition(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "_downloads_dir", lambda: tmp_path)
    cm = _mock_get([b"data"], headers={"Content-Disposition": 'attachment; filename="report.pdf"'})
    with patch("requests.get", return_value=cm):
        download_file("https://example.com/d?id=99")
    assert (tmp_path / "report.pdf").exists()


def test_download_refuses_oversized_content_length(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "_downloads_dir", lambda: tmp_path)
    cm = _mock_get([b"x"], headers={"Content-Length": str(dl.MAX_BYTES + 1)})
    with patch("requests.get", return_value=cm):
        result = download_file("https://example.com/huge.bin")
    assert "refused" in result.lower()
    assert not any(tmp_path.iterdir())


def test_download_aborts_when_stream_exceeds_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "_downloads_dir", lambda: tmp_path)
    monkeypatch.setattr(dl, "MAX_BYTES", 10)
    cm = _mock_get([b"x" * 8, b"y" * 8])  # 16 bytes, no Content-Length
    with patch("requests.get", return_value=cm):
        result = download_file("https://example.com/sneaky.bin")
    assert "aborted" in result.lower()
    assert not any(tmp_path.iterdir())  # partial file cleaned up


def test_download_never_overwrites(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "_downloads_dir", lambda: tmp_path)
    (tmp_path / "file.bin").write_bytes(b"original")
    cm = _mock_get([b"new"])
    with patch("requests.get", return_value=cm):
        download_file("https://example.com/file.bin")
    assert (tmp_path / "file.bin").read_bytes() == b"original"
    assert (tmp_path / "file (1).bin").read_bytes() == b"new"


def test_download_failure_returns_message(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "_downloads_dir", lambda: tmp_path)
    with patch("requests.get", side_effect=RuntimeError("connection reset")):
        result = download_file("https://example.com/x.txt")
    assert "failed" in result.lower()
    assert "connection reset" in result


def test_download_is_confirm_required():
    assert "download_file" in CONFIRM_REQUIRED_TOOLS
    assert "download_file" not in READ_ONLY_TOOLS
