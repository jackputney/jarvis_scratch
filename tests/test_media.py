"""Media finder tools — Spotlight search and app launchers."""

import platform
from unittest.mock import MagicMock, patch

import pytest

from tools.media import find_file, get_recent_files, open_file


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
    with patch("tools.media.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", returncode=0, stderr="")
        result = find_file("xyznonexistentfile12345")
        assert "No files found" in result


def test_find_file_returns_results():
    with patch("tools.media.subprocess.run") as mock_run:
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
