"""
preflight.py — Quick connectivity check before first run.

Verifies:
  1. ANTHROPIC_API_KEY is set and accepted.
  2. CARTESIA_API_KEY is set (warns if not — will fall back to pyttsx3).
  3. pyaudio can open an input stream (microphone access).
  4. openwakeword models can be loaded.

Run with: python preflight.py
"""

import sys
import os

print("🔍 Jarvis preflight check\n")
errors = []

# -- Load .env ----------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("  ✅ .env loaded")
except Exception as e:
    print(f"  ⚠️  dotenv: {e}")

# -- Anthropic ----------------------------------------------------------------
from config import Config
cfg = Config.load()

if not cfg.anthropic_api_key:
    errors.append("ANTHROPIC_API_KEY is not set in .env")
    print("  ❌ ANTHROPIC_API_KEY missing")
else:
    print("  ✅ ANTHROPIC_API_KEY present — testing…", end=" ", flush=True)
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        msg = client.messages.create(
            model=cfg.claude_model_fast,
            max_tokens=10,
            messages=[{"role": "user", "content": "Say: ok"}],
        )
        print(f"ok ({msg.content[0].text.strip()})")
    except Exception as e:
        errors.append(f"Claude API call failed: {e}")
        print(f"FAILED\n    {e}")

# -- Cartesia -----------------------------------------------------------------
if not cfg.cartesia_api_key:
    print("  ⚠️  CARTESIA_API_KEY missing — will use pyttsx3 fallback (lower quality)")
else:
    print("  ✅ CARTESIA_API_KEY present")

# -- PyAudio / microphone -----------------------------------------------------
print("  🎤 Testing microphone…", end=" ", flush=True)
try:
    import pyaudio
    pa = pyaudio.PyAudio()
    info = pa.get_default_input_device_info()
    pa.terminate()
    print(f"ok (device: {info['name']})")
except Exception as e:
    errors.append(f"Microphone/PyAudio error: {e}")
    print(f"FAILED\n    {e}")

# -- openwakeword -------------------------------------------------------------
print("  👂 Loading openwakeword…", end=" ", flush=True)
try:
    from openwakeword.model import Model
    m = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
    print("ok")
    del m
except Exception as e:
    errors.append(f"openwakeword load failed: {e}")
    print(f"FAILED\n    {e}")

# -- Summary ------------------------------------------------------------------
print()
if errors:
    print(f"❌  {len(errors)} issue(s) found:")
    for err in errors:
        print(f"     • {err}")
    sys.exit(1)
else:
    print("✅  All checks passed — run ./run.sh to start Jarvis.")
