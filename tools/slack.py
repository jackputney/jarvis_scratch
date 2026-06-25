"""Slack integration tools."""

from __future__ import annotations

import os


def _token() -> str:
    return (os.environ.get("SLACK_BOT_TOKEN") or "").strip()


def send_slack_message(channel: str, text: str) -> str:
    token = _token()
    if not token:
        return "Error: Slack bot token not configured. Add it in Hub → Connections."
    try:
        import requests
    except ImportError as exc:
        return f"Slack error: {exc}"
    try:
        resp = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"channel": channel, "text": text or ""},
            timeout=10,
        )
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return f"Slack error: {exc}"
    if not data.get("ok"):
        return f"Slack error: {data.get('error', 'unknown')}"
    return f"Message sent to {channel}"


def read_slack_channel(channel: str, count: int = 10) -> str:
    token = _token()
    if not token:
        return "Error: Slack bot token not configured."
    try:
        import requests
    except ImportError as exc:
        return f"Slack error: {exc}"
    try:
        resp = requests.get(
            "https://slack.com/api/conversations.history",
            headers={"Authorization": f"Bearer {token}"},
            params={"channel": channel, "limit": max(1, min(int(count), 50))},
            timeout=10,
        )
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return f"Slack error: {exc}"
    if not data.get("ok"):
        return f"Slack error: {data.get('error', 'unknown')}"
    lines = [f"[{m.get('user', 'unknown')}]: {m.get('text', '')}" for m in data.get("messages", [])]
    return "\n".join(lines) if lines else "No messages found."
