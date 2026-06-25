"""Tests for the self-update module."""

import subprocess
from unittest.mock import MagicMock, patch, call
import pytest

from updater import check_for_updates, apply_update, restart_jarvis, check_and_prompt_update, RESTART_FLAG


def _completed(stdout="", stderr="", rc=0):
    return subprocess.CompletedProcess([], rc, stdout=stdout, stderr=stderr)


# ── check_for_updates ──────────────────────────────────────────────

@patch("updater._git")
def test_check_up_to_date(mock_git):
    sha = "abc123"
    mock_git.side_effect = [
        _completed(),                      # fetch
        _completed(stdout=sha + "\n"),     # rev-parse HEAD
        _completed(stdout=sha + "\n"),     # rev-parse origin/main
    ]
    result = check_for_updates()
    assert result["available"] is False
    assert result["commits_behind"] == 0


@patch("updater._git")
def test_check_updates_available(mock_git):
    mock_git.side_effect = [
        _completed(),                          # fetch
        _completed(stdout="aaa\n"),            # local HEAD
        _completed(stdout="bbb\n"),            # origin/main
        _completed(stdout="3\n"),              # rev-list --count
    ]
    result = check_for_updates()
    assert result["available"] is True
    assert result["commits_behind"] == 3
    assert result["local_sha"] == "aaa"
    assert result["remote_sha"] == "bbb"


@patch("updater._git")
def test_check_fetch_failure(mock_git):
    mock_git.return_value = _completed(stderr="network error", rc=1)
    result = check_for_updates()
    assert result["available"] is False
    assert "network error" in result["error"]


# ── apply_update ────────────────────────────────────────────────────

@patch("updater._git")
def test_apply_success(mock_git):
    mock_git.side_effect = [
        _completed(stdout="old\n"),   # rev-parse HEAD (before)
        _completed(),                  # pull --ff-only
        _completed(stdout="new\n"),   # rev-parse HEAD (after)
    ]
    result = apply_update()
    assert result["success"] is True
    assert result["old_sha"] == "old"
    assert result["new_sha"] == "new"
    assert result["error"] is None


@patch("updater._git")
def test_apply_ff_only_failure(mock_git):
    mock_git.side_effect = [
        _completed(stdout="old\n"),                          # rev-parse HEAD
        _completed(stderr="Not possible to fast-forward", rc=1),  # pull fails
    ]
    result = apply_update()
    assert result["success"] is False
    assert "fast-forward" in result["error"]
    assert result["old_sha"] == "old"
    assert result["new_sha"] == "old"


# ── restart_jarvis ──────────────────────────────────────────────────

@patch("updater.sys.exit")
def test_restart_writes_flag_and_exits(mock_exit, tmp_path):
    with patch("updater.RESTART_FLAG", tmp_path / ".restart_pending"):
        from updater import RESTART_FLAG as _  # just for clarity
        restart_jarvis()
    mock_exit.assert_called_once_with(0)
    assert (tmp_path / ".restart_pending").exists()


# ── check_and_prompt_update ─────────────────────────────────────────

@patch("updater.check_for_updates")
def test_prompt_up_to_date(mock_check):
    mock_check.return_value = {"available": False, "local_sha": "x",
                               "remote_sha": "x", "commits_behind": 0}
    assert check_and_prompt_update() == "You're up to date."


@patch("updater.check_for_updates")
def test_prompt_update_available(mock_check):
    mock_check.return_value = {"available": True, "local_sha": "a",
                               "remote_sha": "b", "commits_behind": 5}
    msg = check_and_prompt_update()
    assert "5 new commits" in msg


@patch("updater.check_for_updates")
def test_prompt_single_commit(mock_check):
    mock_check.return_value = {"available": True, "local_sha": "a",
                               "remote_sha": "b", "commits_behind": 1}
    msg = check_and_prompt_update()
    assert "1 new commit" in msg
    assert "commits" not in msg


@patch("updater.check_for_updates")
def test_prompt_error(mock_check):
    mock_check.return_value = {"available": False, "local_sha": "",
                               "remote_sha": "", "commits_behind": 0,
                               "error": "timeout"}
    msg = check_and_prompt_update()
    assert "couldn't check" in msg
