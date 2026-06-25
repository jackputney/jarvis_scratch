"""tests/test_paths.py — Dev vs frozen path resolution."""

from __future__ import annotations

import sys

from paths import (
    bootstrap_app_paths,
    bundle_root,
    config_path,
    dashboard_static_dir,
    dashboard_templates_dir,
    env_path,
    hub_integrations_path,
    is_frozen,
    needs_onboarding,
    user_data_root,
)


def test_is_frozen_false_in_dev():
    assert is_frozen() is False


def test_bundle_root_is_project_in_dev():
    root = bundle_root()
    assert (root / "main.py").is_file()
    assert (root / "dashboard" / "templates" / "index.html").is_file()


def test_user_data_root_is_project_in_dev():
    root = user_data_root()
    assert (root / "main.py").is_file()


def test_frozen_paths_use_meipass_and_app_support(tmp_path, monkeypatch):
    import sys as _sys

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / ".env.example").write_text("ANTHROPIC_API_KEY=your_key\n", encoding="utf-8")
    if _sys.platform == "darwin":
        support = tmp_path / "Library" / "Application Support" / "Jarvis"
        monkeypatch.setenv("HOME", str(tmp_path))
    elif _sys.platform == "win32":
        support = tmp_path / "Jarvis"
        monkeypatch.setenv("APPDATA", str(tmp_path))
    else:
        support = tmp_path / ".local" / "share" / "jarvis"
        monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(_sys, "frozen", True, raising=False)
    monkeypatch.setattr(_sys, "_MEIPASS", str(bundle), raising=False)

    assert bundle_root() == bundle
    assert user_data_root() == support
    assert env_path() == support / ".env"
    assert config_path() == support / "config.json"


def test_bootstrap_copies_env_example(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / ".env.example").write_text(
        "ANTHROPIC_API_KEY=your_anthropic_api_key_here\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)

    bootstrap_app_paths()

    env = user_data_root() / ".env"
    assert env.is_file()
    assert "ANTHROPIC_API_KEY" in env.read_text(encoding="utf-8")


def test_needs_onboarding_when_env_missing(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setattr("paths.user_data_root", lambda: root)
    monkeypatch.setattr("paths.env_path", lambda: root / ".env")
    monkeypatch.setattr("paths.onboarding_marker_path", lambda: root / ".onboarding_complete")

    assert needs_onboarding() is True


def test_needs_onboarding_false_with_marker(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    (root / ".env").write_text("ANTHROPIC_API_KEY=your_key\n", encoding="utf-8")
    (root / ".onboarding_complete").write_text("ok\n", encoding="utf-8")
    monkeypatch.setattr("paths.user_data_root", lambda: root)
    monkeypatch.setattr("paths.env_path", lambda: root / ".env")
    monkeypatch.setattr("paths.onboarding_marker_path", lambda: root / ".onboarding_complete")

    assert needs_onboarding() is False


def test_dashboard_paths_point_into_bundle():
    assert dashboard_static_dir().is_dir()
    assert (dashboard_templates_dir() / "index.html").is_file()


def test_hub_integrations_bundled():
    assert hub_integrations_path().is_file()
