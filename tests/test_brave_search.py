"""Brave Search with DuckDuckGo fallback."""

from unittest.mock import MagicMock, patch

from config import Config
from tools.web import web_search


def test_brave_search_with_key(monkeypatch, temp_env):
    monkeypatch.setenv("BRAVE_API_KEY", "BSA-test-key")
    cfg = Config.load()
    cfg.brave_api_key = "BSA-test-key"
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "web": {"results": [{"title": "Jarvis", "url": "https://example.com", "description": "AI assistant"}]},
    }
    with patch("config.Config.load", return_value=cfg), patch("requests.get", return_value=mock_resp):
        result = web_search("jarvis assistant")
    assert "Jarvis" in result
    assert "example.com" in result


def test_brave_search_ddg_fallback(monkeypatch, temp_env):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    cfg = Config.load()
    cfg.brave_api_key = ""
    with patch("config.Config.load", return_value=cfg), patch("tools.web._ddg_fallback", return_value="DDG hit"):
        assert web_search("test query") == "DDG hit"
