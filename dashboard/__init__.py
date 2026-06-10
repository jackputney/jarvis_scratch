"""dashboard — Flask control panel for Jarvis.

A single localhost-only Flask app (127.0.0.1:7777) started as a daemon thread
from main.py. Serves one HTML page that polls /api/state every 2 seconds, plus
JSON endpoints for spend, memory, settings, and a text-message path into the
same pipeline as voice (minus STT/TTS).
"""
