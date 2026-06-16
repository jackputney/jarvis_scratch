"""
tools/google_gmail.py — Gmail tools for Jarvis (read + send), via the Gmail API.

Read access uses message metadata + snippet only (no full body fetch) to keep
results short and token-cheap. Snippets are cleaned of zero-width marketing
padding and HTML entities before reaching Claude/TTS.
"""

from __future__ import annotations

import base64
import html
import re
from email.mime.text import MIMEText

from tools.google_auth import get_google_service

MAX_RESULTS = 5
SNIPPET_CHARS = 200

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Marketing emails pad snippets with zero-width spacer characters — strip them.
_ZERO_WIDTH_CHARS = "".join(chr(c) for c in (0x200B, 0x200C, 0x200D, 0xFEFF, 0x034F))
_ZERO_WIDTH_RE = re.compile(f"[{_ZERO_WIDTH_CHARS}]")
_MULTI_SPACE_RE = re.compile(r" {2,}")


def get_gmail_service():
    return get_google_service("gmail", "v1")


def _service():
    return get_gmail_service()


def _clean_snippet(snippet: str) -> str:
    cleaned = _ZERO_WIDTH_RE.sub("", html.unescape(snippet))
    return _MULTI_SPACE_RE.sub(" ", cleaned).strip()


def _summarize_messages(service, messages: list[dict]) -> str:
    lines = []
    for msg in messages:
        full = service.users().messages().get(
            userId="me",
            id=msg["id"],
            format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        headers = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
        snippet = _clean_snippet(full.get("snippet", ""))[:SNIPPET_CHARS]
        lines.append(
            f"From: {headers.get('From', '?')} | Subject: {headers.get('Subject', '(no subject)')} "
            f"| {headers.get('Date', '')}\n  {snippet}"
        )
    return "\n".join(lines)


def list_recent_emails(max_results: int = MAX_RESULTS) -> str:
    """Return a short summary of the most recent inbox messages."""
    limit = max(1, min(int(max_results), 20))
    service = _service()
    resp = service.users().messages().list(
        userId="me", maxResults=limit, labelIds=["INBOX"],
    ).execute()
    messages = resp.get("messages", [])
    if not messages:
        return "No messages found."
    return _summarize_messages(service, messages)


def get_unread_emails(max_results: int = MAX_RESULTS) -> str:
    """Return summaries of unread inbox messages."""
    limit = max(1, min(int(max_results), 20))
    service = _service()
    resp = service.users().messages().list(
        userId="me", q="is:unread in:inbox", maxResults=limit,
    ).execute()
    messages = resp.get("messages", [])
    if not messages:
        return "No unread emails in your inbox."
    header = f"Unread emails ({len(messages)}):"
    return header + "\n" + _summarize_messages(service, messages)


def search_emails(query: str, max_results: int = MAX_RESULTS) -> str:
    """Search Gmail using Gmail search syntax (e.g. 'from:alice is:unread')."""
    query = (query or "").strip()
    if not query:
        return "Search query is empty."
    limit = max(1, min(int(max_results), 20))
    service = _service()
    resp = service.users().messages().list(
        userId="me", q=query, maxResults=limit,
    ).execute()
    messages = resp.get("messages", [])
    if not messages:
        return f"No emails found for query: {query!r}"
    return _summarize_messages(service, messages)


def send_email(to: str, subject: str, body: str) -> str:
    """Send a plain-text email from the authenticated account."""
    to = (to or "").strip()
    if not to:
        return "Recipient address is required."
    if not _EMAIL_RE.match(to):
        return f"Invalid email address: {to!r}. Please provide a full address with @ and a domain."
    service = _service()
    message = MIMEText(body or "", "plain", "utf-8")
    message["to"] = to
    message["subject"] = subject or ""
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    msg_id = sent.get("id", "unknown")
    return f"Email sent to {to} (message id: {msg_id})."
