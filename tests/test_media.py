"""Media finder tools — Spotlight search and app launchers."""

import platform
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import pytest

import tools.media as media_mod
from tools.media import find_file, get_recent_files, open_file, open_photos


def test_find_file_registered():
    from tools.registry import TOOL_DEFINITIONS

    names = [t["name"] for t in TOOL_DEFINITIONS]
    assert "find_file" in names
    assert "find_and_open_file" in names
    assert "open_photos" in names


def test_open_downloads_registered():
    from tools.registry import AUTO_ALLOW_TOOLS, READ_ONLY_TOOLS

    assert "open_downloads" in READ_ONLY_TOOLS or "open_downloads" in AUTO_ALLOW_TOOLS


def test_find_file_no_results():
    with patch("tools.media.platform.system", return_value="Darwin"), \
         patch("tools.media.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", returncode=0, stderr="")
        result = find_file("xyznonexistentfile12345")
        assert "No files found" in result


def test_find_file_returns_results():
    with patch("tools.media.platform.system", return_value="Darwin"), \
         patch("tools.media.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="/Users/test/Documents/report.pdf\n/Users/test/Downloads/report2.pdf",
            returncode=0,
            stderr="",
        )
        result = find_file("report")
        assert "report.pdf" in result
        assert "Found" in result


def test_open_file_missing():
    result = open_file("/nonexistent/path/file.txt")
    assert "not found" in result.lower()


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS only")
def test_get_recent_files_returns_string():
    with patch("tools.media.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="/Users/test/Documents/notes.txt",
            returncode=0,
            stderr="",
        )
        result = get_recent_files(5)
        assert isinstance(result, str)


def test_windows_graceful_fallback():
    with patch("tools.media.platform.system", return_value="Windows"):
        result = find_file("test")
        assert "macOS only" in result


def test_open_photos_no_query_opens_app():
    with patch("tools.media.platform.system", return_value="Darwin"), \
         patch("tools.media.subprocess.run") as mock_run:
        mock_run.return_value = CompletedProcess([], 0, stdout="", stderr="")
        result = open_photos()
    assert "Opened Photos" in result


def test_open_photos_query_uses_url_scheme():
    """Regression: open_photos previously activated Photos but didn't search.
    Now passes query via photos://search?q= URL scheme."""
    captured_cmds: list[list] = []

    def fake_run(cmd, **kwargs):
        captured_cmds.append(list(cmd))
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch("tools.media.platform.system", return_value="Darwin"), \
         patch("tools.media.subprocess.run", side_effect=fake_run):
        result = open_photos("sunset")

    # The URL scheme command must include the encoded query
    url_cmds = [c for c in captured_cmds if any("photos://" in arg for arg in c)]
    assert url_cmds, f"Expected photos:// URL command, got: {captured_cmds}"
    assert any("sunset" in arg for arg in url_cmds[0])
    assert "sunset" in result


def test_open_photos_query_url_encodes_spaces():
    """Spaces in the query must be URL-encoded."""
    captured_cmds: list[list] = []

    def fake_run(cmd, **kwargs):
        captured_cmds.append(list(cmd))
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch("tools.media.platform.system", return_value="Darwin"), \
         patch("tools.media.subprocess.run", side_effect=fake_run):
        open_photos("family reunion")

    url_cmds = [c for c in captured_cmds if any("photos://" in arg for arg in c)]
    assert url_cmds
    combined = " ".join(url_cmds[0])
    # Spaces should be encoded as %20 or + in the URL
    assert "family%20reunion" in combined or "family+reunion" in combined


def test_open_photos_windows_returns_error():
    with patch("tools.media.platform.system", return_value="Windows"):
        result = open_photos("cats")
    assert "macOS only" in result
