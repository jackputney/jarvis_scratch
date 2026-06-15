"""Plugin manifest validation."""

from __future__ import annotations

REQUIRED_MANIFEST_KEYS = frozenset({"name", "description", "trigger", "prompt", "risk_tier"})
VALID_RISK_TIERS = frozenset({"read_only", "auto_allow", "confirm_required"})
VALID_TRIGGER_TYPES = frozenset({"cron", "webhook", "voice", "event"})


def validate_manifest(data: dict) -> str | None:
    if not isinstance(data, dict):
        return "manifest must be a JSON object"
    missing = REQUIRED_MANIFEST_KEYS - set(data.keys())
    if missing:
        return f"Missing required keys: {', '.join(sorted(missing))}"
    if data.get("risk_tier") not in VALID_RISK_TIERS:
        return f"Invalid risk_tier: {data.get('risk_tier')}"
    trigger = data.get("trigger", {})
    if not isinstance(trigger, dict):
        return "trigger must be an object"
    trigger_type = trigger.get("type")
    if trigger_type not in VALID_TRIGGER_TYPES:
        return f"Invalid trigger type: {trigger_type}"
    if trigger_type == "cron" and "schedule" not in trigger:
        return "Cron trigger requires 'schedule' field"
    if trigger_type == "webhook" and "path" not in trigger:
        return "Webhook trigger requires 'path' field"
    name = data.get("name", "")
    if not isinstance(name, str) or not name.replace("_", "").isalnum():
        return "Name must be snake_case alphanumeric"
    return None
