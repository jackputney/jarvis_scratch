"""Plugin manifest discovery."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from plugins.manifest import validate_manifest

logger = logging.getLogger(__name__)
DEFAULT_PLUGINS_DIR = Path(__file__).resolve().parent


def discover_plugins(plugins_dir: Path | str | None = None) -> list[dict]:
    base = Path(plugins_dir) if plugins_dir is not None else DEFAULT_PLUGINS_DIR
    if not base.is_dir():
        return []
    plugins: list[dict] = []
    for manifest_path in sorted(base.glob("*/manifest.json")):
        slug = manifest_path.parent.name
        if slug.startswith("."):
            continue
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
