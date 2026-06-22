"""ElevenLabs TTS provider, router fallback, and dashboard voice picker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from config import Config, ELEVENLABS_VOICES
from dashboard.app import create_app
from tts.errors import TTSError


@pytest.fixture
def client(temp_env):
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_config_defaults():
    cfg = Config()
    assert cfg.tts_provider == "elevenlabs"
    assert cfg.elevenlabs_voice_id == "JBFqnCBsd6RMkjVDRZzb"
    assert cfg.elevenlabs_model_id == "eleven_flash_v2_5"
    assert len(ELEVENLABS_VOICES) == 4
    names = {v["name"] for v in ELEVENLABS_VOICES}
    assert names == {"George", "Liam", "Sarah", "Charlotte"}


def test_elevenlabs_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    from tts import elevenlabs

    with pytest.raises(TTSError, match="ELEVENLABS_API_KEY"):
        elevenlabs.speak("Hello", voice_id="JBFqnCBsd6RMkjVDRZzb")


def test_elevenlabs_speaks_with_correct_voice_id(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    captured: dict = {}

    def fake_iter(text, voice_id, model_id, api_key):
        captured.update({
            "text": text,
            "voice_id": voice_id,
            "model_id": model_id,
            "api_key": api_key,
        })
        return iter([b"\x00\x01" * 100])

    with patch("tts.elevenlabs._iter_elevenlabs_audio", side_effect=fake_iter), \
         patch("tts.elevenlabs._play_pcm_stream") as play:
        from tts import elevenlabs

        elevenlabs.speak("Hi there", voice_id="TX3LPaxmHKxFdv7VOQHJ", model_id="eleven_flash_v2_5")
        play.assert_called_once()
        assert captured["voice_id"] == "TX3LPaxmHKxFdv7VOQHJ"
        assert captured["model_id"] == "eleven_flash_v2_5"
        assert captured["text"] == "Hi there"
        assert captured["api_key"] == "test-key"


def test_elevenlabs_output_format_free_tier():
    from tts import elevenlabs

    assert elevenlabs.OUTPUT_FORMAT == "pcm_16000"
    assert elevenlabs.ELEVENLABS_SAMPLE_RATE == 16000


def test_router_falls_back_to_cartesia_on_tts_error(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    cartesia_calls: list[tuple] = []

    def fake_cartesia(text, voice_id, **kwargs):
        cartesia_calls.append((text, voice_id))

    with patch("tts.elevenlabs.speak", side_effect=TTSError("API down")), \
         patch("tts.cartesia.speak_cartesia", side_effect=fake_cartesia):
        from tts.router import speak

        speak("Fallback please")
        assert cartesia_calls == [("Fallback please", Config().cartesia_voice_id)]


def test_router_falls_back_to_cartesia_without_api_key(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setattr("config._load_dotenv_if_present", lambda: None)
    cartesia_calls: list[str] = []

    with patch("tts.cartesia.speak_cartesia", side_effect=lambda text, *_a, **_k: cartesia_calls.append(text)):
        from tts.router import speak

        speak("No key fallback")
        assert cartesia_calls == ["No key fallback"]


def test_tts_voices_endpoint(client):
    resp = client.get("/api/tts/voices")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["voices"]) == 4
    assert data["selected"] == "JBFqnCBsd6RMkjVDRZzb"
    assert data["provider"] == "elevenlabs"


def test_preview_endpoint_returns_ok(client, monkeypatch):
    ran: list[tuple] = []

    def fake_preview(text, voice_id, *, provider=None):
        ran.append((text, voice_id, provider))

    monkeypatch.setattr("tts.router.speak_preview", fake_preview)

    def _immediate_thread(*_args, **kwargs):
        kwargs["target"]()
        return MagicMock()

    monkeypatch.setattr("dashboard.app.threading.Thread", _immediate_thread)

    resp = client.post(
        "/api/tts/preview",
        json={"voice_id": "JBFqnCBsd6RMkjVDRZzb", "text": "Test preview"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert ran == [("Test preview", "JBFqnCBsd6RMkjVDRZzb", "elevenlabs")]


def test_preview_endpoint_requires_voice_id(client):
    resp = client.post("/api/tts/preview", json={"text": "Hello"})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_router_reloads_voice_after_config_change(temp_env, monkeypatch):
    """Voice/provider changes via dashboard must apply on the next speak() without restart."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    voices: list[str] = []

    def fake_elevenlabs(text, voice_id, model_id, on_first_chunk=None):
        voices.append(voice_id)

    monkeypatch.setattr("tts.elevenlabs.speak", fake_elevenlabs)
    Config.update_persisted({"tts_provider": "elevenlabs", "elevenlabs_voice_id": "JBFqnCBsd6RMkjVDRZzb"})
    from tts.router import speak

    speak("Hello George")
    Config.update_persisted({"elevenlabs_voice_id": "EXAVITQu4vr4xnSDxMaL"})
    speak("Hello Sarah")
    assert voices == ["JBFqnCBsd6RMkjVDRZzb", "EXAVITQu4vr4xnSDxMaL"]


def test_speak_stream_reloads_config_per_chunk(temp_env, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    voices: list[str] = []

    def fake_elevenlabs(text, voice_id, model_id, on_first_chunk=None):
        voices.append(voice_id)

    monkeypatch.setattr("tts.elevenlabs.speak", fake_elevenlabs)
    Config.update_persisted({"tts_provider": "elevenlabs", "elevenlabs_voice_id": "JBFqnCBsd6RMkjVDRZzb"})
    from tts.router import speak_stream

    def chunks():
        yield "First."
        Config.update_persisted({"elevenlabs_voice_id": "EXAVITQu4vr4xnSDxMaL"})
        yield "Second."

    speak_stream(chunks())
    assert voices == ["JBFqnCBsd6RMkjVDRZzb", "EXAVITQu4vr4xnSDxMaL"]
