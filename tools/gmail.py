"""Gmail tools for Jarvis."""

from __future__ import annotations

import base64
from email.mime.text import MIMEText

from tools.google_auth import get_google_service


def get_gmail_service():
    return get_google_service("gmail", "v1")


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _format_message(service, msg_id: str) -> str:
    msg = service.users().messages().get(userId="me", id=msg_id, format="metadata").execute()
    headers = msg.get("payload", {}).get("headers", [])
    sender = _header(headers, "From") or "unknown sender"
    subject = _header(headers, "Subject") or "(no subject)"
    snippet = (msg.get("snippet") or "").strip()
    return f"- From: {sender}\n  Subject: {subject}\n  Snippet: {snippet}"


def get_unread_emails(max_results: int = 5) -> str:
    """Return summaries of unread inbox messages."""
    limit = max(1, min(int(max_results), 20))
    service = get_gmail_service()
    result = (
        service.users()
        .messages()
        .list(userId="me", q="is:unread in:inbox", maxResults=limit)
        .execute()
    )
    messages = result.get("messages") or []
    if not messages:
        return "No unread emails in your inbox."
    lines = [f"Unread emails ({len(messages)}):"]
    for item in messages:
        lines.append(_format_message(service, item["id"]))
    return "\n".join(lines)


def search_emails(query: str) -> str:
    """Search the inbox by Gmail query syntax."""
    query = (query or "").strip()
    if not query:
        return "Search query is empty."
    service = get_gmail_service()
    result = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=10)
        .execute()
    )
    messages = result.get("messages") or []
    if not messages:
        return f"No emails matched: {query!r}"
    lines = [f"Search results for {query!r} ({len(messages)}):"]
    for item in messages:
        lines.append(_format_message(service, item["id"]))
    return "\n".join(lines)


def send_email(to: str, subject: str, body: str) -> str:
    """Send a plain-text email. Requires confirm gate when enabled."""
    to = (to or "").strip()
    if not to:
        return "Recipient address is required."
    message = MIMEText(body or "", "plain", "utf-8")
    message["to"] = to
    message["subject"] = subject or ""
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    service = get_gmail_service()
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    msg_id = sent.get("id", "unknown")
    return f"Email sent to {to} (message id: {msg_id})."
