"""tests/test_onboarding.py — First-run wizard helpers (no GUI)."""

from __future__ import annotations

from unittest.mock import patch


def test_validate_anthropic_key_format_rejects_empty():
    from onboarding import validate_anthropic_key_format

    ok, msg = validate_anthropic_key_format("")
    assert ok is False
    assert "required" in msg.lower()


def test_validate_anthropic_key_format_rejects_placeholder():
    from onboarding import validate_anthropic_key_format

    ok, msg = validate_anthropic_key_format("your_anthropic_api_key_here")
    assert ok is False


def test_validate_anthropic_key_format_accepts_prefix():
    from onboarding import validate_anthropic_key_format

    ok, msg = validate_anthropic_key_format("sk-ant-api03-test")
    assert ok is True
    assert msg == ""


def test_validate_anthropic_key_skips_network_when_disabled():
    from onboarding import validate_anthropic_key

    ok, msg = validate_anthropic_key("sk-ant-api03-test", network=False)
    assert ok is True


def test_validate_anthropic_key_calls_api_when_enabled():
    from onboarding import validate_anthropic_key

    with patch("anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.return_value = object()
        ok, msg = validate_anthropic_key("sk-ant-api03-test", network=True)
    assert ok is True
    assert msg == ""
    mock_cls.return_value.messages.create.assert_called_once()


def test_write_env_file_creates_and_updates(tmp_path):
    from onboarding import write_env_file

    target = tmp_path / ".env"
    write_env_file("sk-ant-one", "cartesia-key", target=target)
    text = target.read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY=sk-ant-one" in text
    assert "CARTESIA_API_KEY=cartesia-key" in text

    write_env_file("sk-ant-two", target=target)
    text = target.read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY=sk-ant-two" in text
    assert "CARTESIA_API_KEY=cartesia-key" in text


def test_write_env_file_omits_blank_cartesia(tmp_path):
    from onboarding import write_env_file

    target = tmp_path / ".env"
    write_env_file("sk-ant-one", "", target=target)
    assert "CARTESIA_API_KEY" not in target.read_text(encoding="utf-8")


def test_mark_onboarding_complete(tmp_path, monkeypatch):
    import paths

    monkeypatch.setattr(paths, "user_data_root", lambda: tmp_path)
    monkeypatch.setattr(paths, "onboarding_marker_path", lambda: tmp_path / ".onboarding_complete")

    paths.mark_onboarding_complete()
    assert (tmp_path / ".onboarding_complete").is_file()
