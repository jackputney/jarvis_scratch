"""paths.py — Resolve bundle vs user-writable paths for dev and PyInstaller builds.

When frozen (PyInstaller), read-only assets live under sys._MEIPASS and all
writable state (.env, config.json, memory, user plugins) lives under the
platform user-data directory:

  macOS:   ~/Library/Application Support/Jarvis/
  Windows: %APPDATA%/Jarvis/
  Linux:   ~/.local/share/jarvis/
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_LAUNCH_AGENT_LABEL = "com.jarvis.app"
_PLACEHOLDER_PREFIXES = ("your_", "sk-ant-your", "sk-ant-api")

LAUNCH_AGENT_LABEL = _LAUNCH_AGENT_LABEL


def is_frozen() -> bool:
    """True when running inside a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    """Read-only project / bundle root (code + static assets)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def user_data_root() -> Path:
    """Writable per-user data directory."""
    if is_frozen():
        if sys.platform == "darwin":
            root = Path.home() / "Library" / "Application Support" / "Jarvis"
        elif sys.platform == "win32":
            root = Path(os.environ.get("APPDATA", str(Path.home()))) / "Jarvis"
        else:
            root = Path.home() / ".local" / "share" / "jarvis"
        root.mkdir(parents=True, exist_ok=True)
        return root
    return Path(__file__).resolve().parent


def user_memory_root() -> Path:
    """Default memory folder when memory_root_path is unset."""
    path = user_data_root() / "memory"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_plugins_dir() -> Path:
    """User-created plugins (writable). Bundled plugins stay in the bundle."""
    path = user_data_root() / "plugins"
    path.mkdir(parents=True, exist_ok=True)
    return path


def bundled_plugins_dir() -> Path:
    return bundle_root() / "plugins"


def env_path() -> Path:
    return user_data_root() / ".env"


def env_example_path() -> Path:
    bundled = bundle_root() / ".env.example"
    if bundled.is_file():
        return bundled
    return user_data_root() / ".env.example"


def config_path() -> Path:
    return user_data_root() / "config.json"


def onboarding_marker_path() -> Path:
    return user_data_root() / ".onboarding_complete"


def dashboard_dir() -> Path:
    return bundle_root() / "dashboard"


def dashboard_static_dir() -> Path:
    return dashboard_dir() / "static"


def dashboard_templates_dir() -> Path:
    return dashboard_dir() / "templates"


def dashboard_url(path: str = "") -> str:
    """Local Flask dashboard base URL (browser and PyWebView fallback)."""
    from dashboard.app import HOST, PORT

    base = f"http://{HOST}:{PORT}"
    if not path:
        return base
    return f"{base}/{path.lstrip('/')}"


def hub_integrations_path() -> Path:
    return bundle_root() / "hub" / "integrations.json"


def log_dir() -> Path:
    if sys.platform == "darwin":
        path = Path.home() / "Library" / "Logs" / "Jarvis"
    elif is_frozen():
        path = user_data_root() / "logs"
    else:
        return user_data_root()
    path.mkdir(parents=True, exist_ok=True)
    return path


def launch_agent_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"


def launch_agent_working_directory() -> Path:
    return user_data_root()


def launch_agent_program_arguments() -> list[str]:
    """Executable argv for LaunchAgent — Jarvis.app binary or dev venv python + main.py."""
    if is_frozen():
        return [str(Path(sys.executable).resolve())]
    root = bundle_root()
    venv_python = root / ".venv" / "bin" / "python"
    # Keep the .venv/bin/python path — do NOT resolve() the symlink or launchd
    # runs the system interpreter without the virtualenv site-packages.
    if venv_python.exists():
        python = str(venv_python)
    else:
        python = str(Path(sys.executable))
    return [python, str((root / "main.py").resolve())]


def launch_agent_log_paths() -> tuple[Path, Path]:
    logs = log_dir()
    return logs / "launchd.stdout.log", logs / "launchd.stderr.log"


def launch_at_login_mode() -> str:
    """'frozen' when bundled as .app, otherwise 'dev'."""
    return "frozen" if is_frozen() else "dev"


def launched_by_launchd() -> bool:
    """True when macOS launchd started this process (login item / LaunchAgent)."""
    if os.environ.get("JARVIS_LAUNCHD") == "1":
        return True
    return os.environ.get("XPC_SERVICE_NAME") == LAUNCH_AGENT_LABEL


def _read_env_value(key: str) -> str:
    path = env_path()
    if not path.is_file():
        return ""
    prefix = f"{key}="
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _is_placeholder_secret(value: str) -> bool:
    val = value.strip()
    if not val:
        return True
    lower = val.lower()
    return any(lower.startswith(p) for p in _PLACEHOLDER_PREFIXES)


def needs_onboarding() -> bool:
    """True when first-run setup should run before Jarvis starts."""
    if onboarding_marker_path().is_file():
        return False
    key = _read_env_value("ANTHROPIC_API_KEY")
    if _is_placeholder_secret(key):
        return True
    return not env_path().is_file()


def bootstrap_app_paths() -> None:
    """Ensure user-data layout exists; seed .env from the bundled example."""
    root = user_data_root()
    root.mkdir(parents=True, exist_ok=True)
    user_memory_root()
    user_plugins_dir()

    env = env_path()
    if not env.is_file():
        example = env_example_path()
        if example.is_file():
            shutil.copy(example, env)


def mark_onboarding_complete() -> None:
    onboarding_marker_path().write_text("ok\n", encoding="utf-8")
