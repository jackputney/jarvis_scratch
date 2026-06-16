"""Pitch deck generator — Claude content + python-pptx."""

import json
from unittest.mock import MagicMock, patch

import pytest


def test_create_pitch_deck_registered():
    from tools.registry import TOOL_DEFINITIONS

    names = [t["name"] for t in TOOL_DEFINITIONS]
    assert "create_pitch_deck" in names


def test_create_pitch_deck_confirm_required():
    from tools.registry import CONFIRM_REQUIRED_TOOLS

    assert "create_pitch_deck" in CONFIRM_REQUIRED_TOOLS


def test_fallback_slide_content():
    from tools.pitch_deck import _fallback_slide_content

    slides = _fallback_slide_content("Test Topic", 5)
    assert len(slides) == 5
    assert slides[0]["title"] == "Test Topic"
    assert all("title" in s for s in slides)
    assert all("bullets" in s for s in slides)


def test_fallback_slide_count_respected():
    from tools.pitch_deck import _fallback_slide_content

    slides = _fallback_slide_content("Topic", 3)
    assert len(slides) == 3


def test_generate_slide_content_parses_json():
    from tools.pitch_deck import _generate_slide_content

    mock_response = json.dumps([
        {"title": "Test", "subtitle": "Sub", "bullets": ["A", "B"], "notes": "Note"},
        {"title": "Slide 2", "bullets": ["C", "D"], "notes": ""},
    ])
    mock_content = MagicMock()
    mock_content.text = mock_response
    mock_message = MagicMock()
    mock_message.content = [mock_content]
    with patch("anthropic.Anthropic") as mock_client:
        mock_client.return_value.messages.create.return_value = mock_message
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            slides = _generate_slide_content("Test", 2, "professional")
    assert len(slides) == 2
    assert slides[0]["title"] == "Test"


def test_create_pitch_deck_no_pptx_installed():
    import tools.pitch_deck as pitch_mod

    real_import = __builtins__["__import__"]

    def fake_import(name, *args, **kwargs):
        if name == "pptx" or name.startswith("pptx."):
            raise ImportError("no pptx")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        result = pitch_mod.create_pitch_deck("Test Topic")
    assert "python-pptx is not installed" in result


def test_create_pitch_deck_writes_file(tmp_path, monkeypatch):
    from tools.pitch_deck import create_pitch_deck

    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    with patch("tools.pitch_deck.subprocess.run"):
        result = create_pitch_deck("Quantum PRM", slide_count=3, output_dir=str(tmp_path))
    assert "Pitch deck created" in result
    files = list(tmp_path.glob("*.pptx"))
    assert len(files) == 1
    assert files[0].stat().st_size > 0


def test_create_pitch_deck_empty_topic():
    from tools.pitch_deck import create_pitch_deck

    assert "Refused" in create_pitch_deck("")
