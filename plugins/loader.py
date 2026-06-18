"""Plugin manifest discovery."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from plugins.manifest import validate_manifest

logger = logging.getLogger(__name__)
DEFAULT_PLUGINS_DIR = Path(__file__).resolve().parent


def _plugin_dirs(plugins_dir: Path | str | None) -> list[Path]:
    if plugins_dir is not None:
        return [Path(plugins_dir)]
    from paths import bundled_plugins_dir, user_plugins_dir

    dirs: list[Path] = []
    bundled = bundled_plugins_dir()
    if bundled.is_dir():
        dirs.append(bundled)
    user = user_plugins_dir()
    if user.is_dir() and user != bundled:
        dirs.append(user)
    if not dirs:
        dirs.append(DEFAULT_PLUGINS_DIR)
    return dirs


def discover_plugins(plugins_dir: Path | str | None = None) -> list[dict]:
    seen_slugs: set[str] = set()
    plugins: list[dict] = []
    for base in _plugin_dirs(plugins_dir):
        if not base.is_dir():
            continue
        for manifest_path in sorted(base.glob("*/manifest.json")):
            slug = manifest_path.parent.name
            if slug.startswith(".") or slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Skipped invalid manifest %s: %s", manifest_path, exc)
                continue
            err = validate_manifest(data)
            if err:
                logger.warning("Skipped manifest %s: %s", manifest_path, err)
                continue
            data["_path"] = str(manifest_path)
            data["_dir"] = str(manifest_path.parent)
            data["_slug"] = slug
            data["enabled"] = not (manifest_path.parent / ".disabled").is_file()
            plugins.append(data)
            logger.info("Loaded plugin: %s", data.get("name", slug))
    return plugins
