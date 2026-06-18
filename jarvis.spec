# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — builds dist/Jarvis.app (macOS one-folder bundle).

Run via build_mac.sh (macOS only). Windows/dev continues to use run.ps1 / run.sh.
"""

from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None
project_root = Path(SPECPATH)

datas: list = [
    (str(project_root / "dashboard" / "templates"), "dashboard/templates"),
    (str(project_root / "dashboard" / "static"), "dashboard/static"),
    (str(project_root / "hub" / "integrations.json"), "hub"),
    (str(project_root / "plugins"), "plugins"),
    (str(project_root / ".env.example"), "."),
]
binaries: list = []
hiddenimports: list = collect_submodules("orchestrator") + collect_submodules("tools") + [
    "paths",
    "onboarding",
    "pipeline",
    "config",
    "conversation",
    "costs",
    "events",
    "preflight",
    "PyQt6",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.sip",
    "flask",
    "werkzeug",
    "jinja2",
    "anthropic",
    "openai",
    "google.genai",
    "cartesia",
    "sounddevice",
    "pynput",
    "pynput.keyboard",
    "pynput.keyboard._darwin",
    "webview",
    "pywebview",
    "onnxruntime",
    "openwakeword",
    "webrtcvad",
    "faster_whisper",
    "mlx_whisper",
    "pptx",
    "dotenv",
    "sqlite3",
    "hub.registry",
    "dashboard.app",
    "dashboard.window",
    "dashboard.hub_routes",
    "plugins.loader",
    "plugins.scheduler",
    "memory.db",
    "memory.store",
    "memory.semantic",
    "ui.face",
    "tts.cartesia",
    "llm.router",
    "llm.openai_client",
    "llm.gemini_client",
]

# Pull in dynamic libraries and data for heavy optional deps (best-effort).
for package in (
    "mlx_whisper",
    "mlx",
    "onnxruntime",
    "openwakeword",
    "faster_whisper",
    "sounddevice",
    "PyQt6",
    "cartesia",
    "pywebview",
):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception:
        pass

try:
    datas += collect_data_files("flask")
except Exception:
    pass

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Jarvis",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Jarvis",
)

app = BUNDLE(
    coll,
    name="Jarvis.app",
    icon=None,
    bundle_identifier="com.jarvis.voiceassistant",
    info_plist={
        "CFBundleName": "Jarvis",
        "CFBundleDisplayName": "Jarvis",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "NSMicrophoneUsageDescription": (
            "Jarvis uses the microphone for wake word detection and voice commands."
        ),
        "NSAppleEventsUsageDescription": (
            "Jarvis automates macOS apps and system settings when you ask."
        ),
        "LSUIElement": True,
    },
)
