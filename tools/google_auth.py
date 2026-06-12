"""
tools/google_auth.py — Google OAuth for Calendar, Gmail, and Sheets.

Builds OAuth client config from GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env
vars at runtime (no credentials.json file on disk). On first use, opens the
browser for sign-in and stores the refresh token in memory/google_token.json.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build

logger = logging.getLogger("jarvis.tools.google")

TOKEN_PATH = Path(__file__).resolve().parent.parent / "memory" / "google_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _client_config() -> dict:
    from config import Config

    cfg = Config.load()
    client_id = (cfg.google_client_id or os.environ.get("GOOGLE_CLIENT_ID", "")).strip()
    client_secret = (cfg.google_client_secret or os.environ.get("GOOGLE_CLIENT_SECRET", "")).strip()
    if not client_id or not client_secret:
        raise RuntimeError(
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in .env "
            "(see .env.example). Restart Jarvis after editing .env."
        )
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def _save_token(creds: Credentials) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    logger.info("🔐 Google token saved to %s", TOKEN_PATH.name)


def get_credentials() -> Credentials:
    """Return valid Google credentials, refreshing or running OAuth as needed."""
    creds: Credentials | None = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_token(creds)
        return creds

    print("🌐 Opening browser for Google sign-in — this only happens once.")
    flow = InstalledAppFlow.from_client_config(_client_config(), SCOPES)
    creds = flow.run_local_server(port=0)
    _save_token(creds)
    return creds


def get_google_service(api_name: str, api_version: str) -> Resource:
    """Build an authenticated Google API client."""
    return build(api_name, api_version, credentials=get_credentials(), cache_discovery=False)


def ensure_google_ready(*, interactive: bool = True) -> bool:
    """Load or refresh credentials at startup — never mid-voice on first OAuth.

    Returns True if Google tools are ready, False if credentials are not configured.
    When interactive=True and no token exists yet, opens the browser once before
    the voice loop starts.
    """
    try:
        _client_config()
    except RuntimeError:
        return False

    if TOKEN_PATH.exists():
        get_credentials()
        return True

    if not interactive:
        logger.info("🔐 Google token missing — sign in via dashboard or restart with browser.")
        return False

    logger.info("🔐 Google sign-in required — opening browser (one-time setup).")
    get_credentials()
    return True
