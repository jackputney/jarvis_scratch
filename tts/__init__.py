"""tts — Text-to-speech layer for Jarvis.

Primary: Cartesia Sonic API with streaming audio to pyaudio (first chunk ~150ms).
Fallback: pyttsx3 local TTS when CARTESIA_API_KEY is not set.
"""
