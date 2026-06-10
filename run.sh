#!/usr/bin/env bash
# run.sh — one command to launch Jarvis.
#
# Checks the environment and installs anything missing before launching:
#   • PortAudio (Homebrew) — required by PyAudio
#   • a Python virtualenv at .venv
#   • the pinned Python dependencies
#
# Usage: ./run.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "🚀 Starting Jarvis…"

# --- PortAudio (needed by PyAudio) ---------------------------------------
if [[ "$(uname)" == "Darwin" ]]; then
  if ! brew list portaudio >/dev/null 2>&1; then
    echo "🔊 Installing PortAudio (needed for the microphone)…"
    brew install portaudio
  else
    echo "✅ PortAudio present."
  fi
fi

# --- Virtualenv -----------------------------------------------------------
if [[ ! -d .venv ]]; then
  echo "🐍 Creating virtualenv (.venv)…"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# --- Dependencies ---------------------------------------------------------
# Fast check: if the key imports succeed we skip the (slow) pip install.
if ! python -c "import anthropic, flask, PyQt6, pyaudio, mlx_whisper, openwakeword" >/dev/null 2>&1; then
  echo "📦 Installing Python dependencies (first run / new deps)…"
  python -m pip install --upgrade pip >/dev/null
  python -m pip install -r requirements.txt
else
  echo "✅ Dependencies present."
fi

# --- .env -----------------------------------------------------------------
if [[ ! -f .env ]]; then
  echo "🔑 No .env found — copying .env.example. Add your ANTHROPIC_API_KEY before talking."
  cp .env.example .env
fi

echo "✅ Environment ready — launching."
python main.py "$@"
