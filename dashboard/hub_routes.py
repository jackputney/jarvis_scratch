"""Jarvis Hub API routes — integrations, keys, OAuth, plugins, health."""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

import costs
from config import Config
from hub.registry import (
    FIELD_TO_CONFIG,
    config_updates_from_fields,
    get_integration,
    get_status,
    integration_field_keys,
    load_integrations,
)

logger = logging.getLogger("jarvis.hub")

hub_bp = Blueprint("hub", __name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
PLUGINS_DIR = PROJECT_ROOT / "plugins"

PLUGIN_GENERATOR_PROMPT = """You generate Jarvis plugin manifests. Return ONLY valid JSON matching this schema — no explanation, no markdown fences:
{
  "name": string (snake_case),
  "description": string,
  "trigger": { "type": "cron"|"webhook"|"voice"|"event", ...type-specific fields },
  "prompt": string (the instruction Jarvis runs when triggered),
  "risk_tier": "read_only"|"auto_allow"|"confirm_required",
  "requires": [list of integration ids this plugin needs]
}
For cron triggers include "schedule" (cron expression). For webhook triggers include "path" (e.g. "/hooks/github"). For event triggers include "on" (e.g. "job.done")."""


def _write_env_updates(updates: dict[str, str], env_path: Path | None = None) -> None:
    """Append or overwrite keys in .env without logging secret values."""
    path = env_path or ENV_PATH
    lines: list[str] = []
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()
    written: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                written.add(key)
                continue
        new_lines.append(line)
    for key, value in updates.items():
        if key not in written:
            new_lines.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(new_lines)
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")


def _parse_manifest_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("manifest must be a JSON object")
    return data


def _orchestrator_snapshot() -> dict[str, Any]:
    try:
        from orchestrator.runtime import get_orchestrator

        orch = get_orchestrator()
        current = getattr(orch, "_current_job_id", None)
        depth = orch.queue_depth() if hasattr(orch, "queue_depth") else 0
        return {"queue_depth": depth, "current_job": current}
    except Exception:  # noqa: BLE001
        return {"queue_depth": 0, "current_job": None}


def _plugin_counts() -> dict[str, int]:
    total = 0
    active = 0
    if PLUGINS_DIR.is_dir():
        for entry in PLUGINS_DIR.iterdir():
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if not (entry / "manifest.json").is_file():
                continue
            total += 1
            if not (entry / ".disabled").is_file():
                active += 1
    return {"total": total, "active": active}


def list_plugin_manifests() -> list[dict[str, Any]]:
    """Return every plugin under plugins/*/manifest.json."""
    results: list[dict[str, Any]] = []
    if not PLUGINS_DIR.is_dir():
        return results
    for entry in sorted(PLUGINS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        manifest_path = entry / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            manifest = {"name": entry.name, "description": "(invalid manifest)"}
        results.append({
            "slug": entry.name,
            "path": str(manifest_path.relative_to(PROJECT_ROOT)),
            "enabled": not (entry / ".disabled").is_file(),
            "manifest": manifest,
        })
    return results


@hub_bp.route("/api/hub/integrations")
def api_hub_integrations():  # noqa: ANN202
    cfg = Config.load()
    merged = []
    for item in load_integrations():
        status = get_status(item["id"], cfg)
        merged.append({**item, **status})
    return jsonify(merged)


@hub_bp.route("/api/hub/status")
def api_hub_status():  # noqa: ANN202
    cfg = Config.load()
    services = [get_status(i["id"], cfg) for i in load_integrations()]
    spend_summary = costs.get_spend_summary(cfg.daily_budget_usd, cfg.monthly_budget_usd)
    remaining = max(0.0, cfg.monthly_budget_usd - spend_summary.get("month", 0.0))
    return jsonify({
        "services": services,
        "orchestrator": _orchestrator_snapshot(),
        "plugins": _plugin_counts(),
        "spend": {
            "today": spend_summary.get("today", 0.0),
            "month": spend_summary.get("month", 0.0),
            "remaining": round(remaining, 4),
        },
    })


@hub_bp.route("/api/hub/keys", methods=["POST"])
def api_hub_keys():  # noqa: ANN202
    body = request.get_json(silent=True) or {}
    integration_id = (body.get("integration_id") or "").strip()
    fields = body.get("fields") or {}
    if not integration_id:
        return jsonify({"error": "integration_id is required"}), 400
    if not isinstance(fields, dict):
        return jsonify({"error": "fields must be an object"}), 400

    integration = get_integration(integration_id)
    if integration is None:
        return jsonify({"error": f"Unknown integration: {integration_id}"}), 404

    allowed = integration_field_keys(integration)
    secret_updates: dict[str, str] = {}
    plain_updates: dict[str, str] = {}
    field_defs = {f["key"]: f for f in integration.get("fields", []) if "key" in f}

    for key, value in fields.items():
        if key not in allowed:
            continue
        text = "" if value is None else str(value).strip()
        if field_defs.get(key, {}).get("secret"):
            if text:
                secret_updates[key] = text
        elif key in FIELD_TO_CONFIG:
            plain_updates[key] = text
        elif text:
            secret_updates[key] = text

    try:
        if secret_updates:
            _write_env_updates(secret_updates)
            for key, val in secret_updates.items():
                import os
                os.environ[key] = val
        config_changes = config_updates_from_fields(plain_updates)
        if config_changes:
            Config.update_persisted(config_changes)
    except Exception as exc:  # noqa: BLE001
        logger.error("Hub key save failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500

    return jsonify({"ok": True})


@hub_bp.route("/api/hub/google/auth", methods=["POST"])
def api_hub_google_auth():  # noqa: ANN202
    def _run() -> None:
        try:
            from tools.google_auth import ensure_google_ready

            ensure_google_ready(interactive=True)
        except Exception as exc:  # noqa: BLE001
            logger.error("Google OAuth failed: %s", exc, exc_info=True)

    threading.Thread(target=_run, daemon=True, name="jarvis-google-oauth").start()
    return jsonify({
        "ok": True,
        "message": "Check your browser to complete Google sign-in",
    })


@hub_bp.route("/api/hub/plugins/generate", methods=["POST"])
def api_hub_plugins_generate():  # noqa: ANN202
    body = request.get_json(silent=True) or {}
    description = (body.get("description") or "").strip()
    if not description:
        return jsonify({"error": "description is required"}), 400

    cfg = Config.load()
    if not cfg.anthropic_api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY is not configured"}), 400

    raw = ""
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        response = client.messages.create(
            model=cfg.claude_model_fast,
            max_tokens=1024,
            system=PLUGIN_GENERATOR_PROMPT,
            messages=[{"role": "user", "content": f"Generate a plugin manifest for: {description}"}],
        )
        parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
        raw = "".join(parts)
        manifest = _parse_manifest_json(raw)
    except json.JSONDecodeError:
        return jsonify({"error": "Claude returned invalid JSON", "raw": raw}), 422
    except Exception as exc:  # noqa: BLE001
        logger.error("Plugin generation failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500

    slug = re.sub(r"[^a-z0-9_]+", "_", manifest.get("name", "plugin").lower()).strip("_")
    if not slug:
        slug = "plugin"
    plugin_dir = PLUGINS_DIR / slug
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = plugin_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    try:
        rel_path = str(manifest_path.relative_to(PROJECT_ROOT))
    except ValueError:
        rel_path = str(manifest_path)
    return jsonify({"ok": True, "manifest": manifest, "path": rel_path, "slug": slug})


@hub_bp.route("/api/hub/plugins/toggle", methods=["POST"])
def api_hub_plugins_toggle():  # noqa: ANN202
    body = request.get_json(silent=True) or {}
    slug = (body.get("slug") or "").strip()
    enabled = body.get("enabled")
    if not slug or not re.fullmatch(r"[a-z0-9_]+", slug):
        return jsonify({"error": "valid slug is required"}), 400
    if not isinstance(enabled, bool):
        return jsonify({"error": "enabled must be a boolean"}), 400

    plugin_dir = PLUGINS_DIR / slug
    manifest_path = plugin_dir / "manifest.json"
    if not manifest_path.is_file():
        return jsonify({"error": "plugin not found"}), 404

    flag = plugin_dir / ".disabled"
    if enabled:
        if flag.is_file():
            flag.unlink()
    else:
        flag.write_text("disabled\n", encoding="utf-8")
    return jsonify({"ok": True, "slug": slug, "enabled": enabled})


@hub_bp.route("/api/hub/plugins/discard", methods=["POST"])
def api_hub_plugins_discard():  # noqa: ANN202
    body = request.get_json(silent=True) or {}
    slug = (body.get("slug") or "").strip()
    if not slug or not re.fullmatch(r"[a-z0-9_]+", slug):
        return jsonify({"error": "valid slug is required"}), 400
    plugin_dir = PLUGINS_DIR / slug
    if not plugin_dir.is_dir():
        return jsonify({"error": "plugin not found"}), 404
    import shutil

    shutil.rmtree(plugin_dir)
    return jsonify({"ok": True})
