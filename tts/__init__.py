"""tts — Text-to-speech layer for Jarvis.

Primary: ElevenLabs streaming (eleven_flash_v2_5).
Fallback: Cartesia Sonic, then pyttsx3 / macOS say.
"""

from tts.router import speak, speak_preview, speak_stream, stop_speech

__all__ = ["speak", "speak_stream", "speak_preview", "stop_speech"]
