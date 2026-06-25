"""
tools/google_gmail.py — Gmail tools for Jarvis (read + send), via the Gmail API.

Read access uses message metadata + snippet only (no full body fetch) to keep
results short and token-cheap. Snippets are cleaned of zero-width marketing
padding and HTML entities before reaching Claude/TTS.
"""

from __future__ import annotations

import base64
import html
import logging
import re
from email.mime.text import MIMEText

from tools.google_auth import get_google_service

logger = logging.getLogger("jarvis.tools.google_gmail")

MAX_RESULTS = 5
SNIPPET_CHARS = 200

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_FROM_EMAIL_RE = re.compile(r"<([^>]+@[^>]+)>")

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


def _extract_email(from_header: str) -> str:
    raw = (from_header or "").strip()
    match = _FROM_EMAIL_RE.search(raw)
    if match:
        return match.group(1).strip()
    if _EMAIL_RE.match(raw):
        return raw
    return ""


def reply_subject(subject: str) -> str:
    s = (subject or "").strip()
    if not s:
        return "Re:"
    if s.lower().startswith("re:"):
        return s
    return f"Re: {s}"


def _fetch_message_summary(service, msg_ref: dict) -> dict:
    full = service.users().messages().get(
        userId="me",
        id=msg_ref["id"],
        format="metadata",
        metadataHeaders=["From", "Subject", "Date"],
    ).execute()
    headers = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
    from_raw = headers.get("From", "?")
    return {
        "id": msg_ref["id"],
        "thread_id": full.get("threadId", ""),
        "from": from_raw,
        "from_email": _extract_email(from_raw),
        "subject": headers.get("Subject", "(no subject)"),
        "date": headers.get("Date", ""),
        "snippet": _clean_snippet(full.get("snippet", ""))[:SNIPPET_CHARS],
    }


def _summarize_messages(service, messages: list[dict]) -> str:
    lines = []
    for msg in messages:
        item = _fetch_message_summary(service, msg)
        lines.append(
            f"From: {item['from']} | Subject: {item['subject']} | {item['date']}\n  {item['snippet']}"
        )
    return "\n".join(lines)


def fetch_unread_emails(max_results: int = MAX_RESULTS) -> list[dict]:
    """Return structured unread inbox messages for the dashboard."""
    limit = max(1, min(int(max_results), 20))
    service = _service()
    resp = service.users().messages().list(
        userId="me", q="is:unread in:inbox", maxResults=limit,
    ).execute()
    messages = resp.get("messages", [])
    return [_fetch_message_summary(service, msg) for msg in messages]


def fetch_thread_context(thread_id: str, max_messages: int = 4) -> str:
    """Return a short metadata summary of recent messages in a thread."""
    thread_id = (thread_id or "").strip()
    if not thread_id:
        return ""
    service = _service()
    try:
        thread = service.users().threads().get(
            userId="me",
            id=thread_id,
            format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_thread_context failed for thread %s: %s", thread_id, exc)
        return ""
    chunks: list[str] = []
    for msg in thread.get("messages", [])[-max(1, min(int(max_messages), 8)):]:
        item = _fetch_message_summary(service, msg)
        chunks.append(
            f"From: {item['from']}\nSubject: {item['subject']}\nDate: {item['date']}\n{item['snippet']}"
        )
    return "\n\n---\n\n".join(chunks)


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
    items = fetch_unread_emails(max_results=max_results)
    if not items:
        return "No unread emails in your inbox."
    header = f"Unread emails ({len(items)}):"
    lines = [
        f"From: {item['from']} | Subject: {item['subject']} | {item['date']}\n  {item['snippet']}"
        for item in items
    ]
    return header + "\n" + "\n".join(lines)


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


_DRAFT_REPLY_SYSTEM = (
    "You draft concise, helpful email replies for the user's assistant dashboard. "
    "Write only the email body plain text: no subject line, no markdown, no placeholders "
    "like [Your name]. Keep the tone natural and professional. "
    "Match the language of the incoming email when it is obvious."
)


def draft_email_reply(
    email: dict,
    *,
    thread_context: str = "",
    model: str,
    api_key: str,
) -> str:
    """Use Claude to draft a reply body for one inbox message."""
    import anthropic

    context_block = ""
    if thread_context.strip():
        context_block = f"\n\nEarlier messages in this thread:\n{thread_context.strip()}"

    user_prompt = (
        f"Draft a reply to this email:\n\n"
        f"From: {email.get('from', '?')}\n"
        f"Date: {email.get('date', '')}\n"
        f"Subject: {email.get('subject', '(no subject)')}\n\n"
        f"{email.get('snippet', '').strip()}"
        f"{context_block}"
    )

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=800,
        system=_DRAFT_REPLY_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
    )
    parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
    body = "".join(parts).strip()
    if not body:
        raise ValueError("Claude returned an empty draft")
    return body


def send_email(to: str, subject: str, body: str) -> str:
    """Send a plain-text email from the authenticated account."""
    if not (subject or "").strip():
        first_line = (body or "").strip().splitlines()[0] if (body or "").strip() else ""
        words = first_line.split()
        subject = " ".join(words[:6]) if words else "(no subject)"
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
