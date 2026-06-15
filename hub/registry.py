"""Hub integration registry — loads integrations.json and reports live status."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from config import Config

INTEGRATIONS_PATH = Path(__file__).parent / "integrations.json"

# Non-secret integration field keys that map to config.json attributes.
FIELD_TO_CONFIG: dict[str, str] = {
    "DAILY_BUDGET_USD": "daily_budget_usd",
}


def _field_value(key: str, cfg: Config) -> str:
    config_attr = FIELD_TO_CONFIG.get(key)
    if config_attr:
        val = getattr(cfg, config_attr, "")
        return "" if val is None else str(val).strip()
    return (os.environ.get(key) or "").strip()


def _oauth_status(integration_id: str) -> dict[str, Any]:
    if integration_id != "google":
        return {
            "id": integration_id,
            "connected": False,
            "label": "Unsupported OAuth provider",
            "detail": None,
        }
    try:
        from tools.google_auth import SCOPES, TOKEN_PATH, _client_config
        from google.oauth2.credentials import Credentials

        try:
            _client_config()
        except RuntimeError:
            return {
                "id": integration_id,
                "connected": False,
                "label": "Not configured",
                "detail": "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env",
            }
        if not TOKEN_PATH.exists():
            return {
                "id": integration_id,
                "connected": False,
                "label": "Not connected",
                "detail": "Complete Google sign-in from Connections",
            }
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        if creds and creds.valid:
            return {"id": integration_id, "connected": True, "label": "Connected", "detail": None}
        if creds and creds.expired and creds.refresh_token:
            return {
                "id": integration_id,
                "connected": True,
                "label": "Connected",
                "detail": "Token expired but refreshable",
            }
        return {
            "id": integration_id,
            "connected": False,
            "label": "Token expired",
            "detail": "Re-authenticate with Google",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "id": integration_id,
            "connected": False,
            "label": "Error",
            "detail": str(exc),
        }


def _api_key_status(integration: dict[str, Any], cfg: Config) -> dict[str, Any]:
    integration_id = integration["id"]
    required_fields = [
        f for f in integration.get("fields", []) if f.get("required")
    ]
    missing = [f["key"] for f in required_fields if not _field_value(f["key"], cfg)]
    if missing:
        return {
            "id": integration_id,
            "connected": False,
            "label": "Not configured",
            "detail": f"Missing: {', '.join(missing)}",
        }
    return {"id": integration_id, "connected": True, "label": "Connected", "detail": None}


@lru_cache(maxsize=1)
def load_integrations() -> list[dict[str, Any]]:
    """Return integration definitions from integrations.json."""
    try:
        with open(INTEGRATIONS_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except Exception:  # noqa: BLE001
        pass
    return []


def get_integration(integration_id: str) -> dict[str, Any] | None:
    for item in load_integrations():
        if item.get("id") == integration_id:
            return item
    return None


def get_status(integration_id: str, config: Config | None = None) -> dict[str, Any]:
    """Return connection status for one integration. Never raises."""
    try:
        integration = get_integration(integration_id)
        if integration is None:
            return {
                "id": integration_id,
                "connected": False,
                "label": "Unknown",
                "detail": "Integration not found",
            }
        cfg = config or Config.load()
        auth_type = integration.get("auth_type", "api_key")
        if auth_type == "oauth":
            return _oauth_status(integration_id)
        return _api_key_status(integration, cfg)
    except Exception as exc:  # noqa: BLE001
        return {
            "id": integration_id,
            "connected": False,
            "label": "Error",
            "detail": str(exc),
        }


def integration_field_keys(integration: dict[str, Any]) -> set[str]:
    return {f["key"] for f in integration.get("fields", []) if "key" in f}


def config_updates_from_fields(fields: dict[str, str]) -> dict[str, Any]:
    """Map hub field keys to config.json attribute names."""
    updates: dict[str, Any] = {}
    for key, value in fields.items():
        attr = FIELD_TO_CONFIG.get(key)
        if attr:
            updates[attr] = value
    return updates
