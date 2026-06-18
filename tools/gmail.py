"""Backward-compatible Gmail re-exports — implementation lives in google_gmail.py."""

from tools.google_gmail import (
    fetch_thread_context,
    fetch_unread_emails,
    get_gmail_service,
    get_unread_emails,
    list_recent_emails,
    search_emails,
    send_email,
)

__all__ = [
    "fetch_thread_context",
    "fetch_unread_emails",
    "get_gmail_service",
    "get_unread_emails",
    "list_recent_emails",
    "search_emails",
    "send_email",
]
