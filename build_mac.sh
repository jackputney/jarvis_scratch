#!/usr/bin/env bash
# build_mac.sh — Build a double-clickable Jarvis.app for macOS (PyInstaller).
#
# Produces:  dist/Jarvis.app
# User data:  ~/Library/Application Support/Jarvis/
# Logs:      ~/Library/Logs/Jarvis/jarvis.log
#
# Usage: ./build_mac.sh
#
# Windows dev is unchanged — keep using run.ps1.
set -euo pipefail
cd "$(dirname "$0")"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "❌  build_mac.sh is macOS only."
  echo "    On Windows, use .\\run.ps1 to launch from source."
  exit 1
fi

echo "📦  Building Jarvis.app with PyInstaller…"

if [[ ! -d .venv ]]; then
  echo "🐍  Creating virtualenv (.venv)…"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "📥  Installing build dependencies…"
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt -q
python -m pip install pyinstaller -q

echo "🧹  Cleaning previous build artefacts…"
rm -rf build dist

echo "🔨  Running PyInstaller (this may take several minutes)…"
python -m PyInstaller jarvis.spec --noconfirm --clean

if [[ ! -d dist/Jarvis.app ]]; then
  echo "❌  Build failed — dist/Jarvis.app not found."
  exit 1
fi

echo ""
echo "✅  Built: dist/Jarvis.app"
echo "   • Drag to /Applications, then double-click to launch"
echo "   • First run opens the setup wizard (Anthropic key → optional Cartesia)"
echo "   • Global hotkey (Ctrl+Shift+Space) registers automatically"
echo "   • User data: ~/Library/Application Support/Jarvis/"
echo "   • Logs: ~/Library/Logs/Jarvis/jarvis.log"
echo ""
echo "   macOS will ask for Microphone and Accessibility permissions on first use."
