"""
tools/dev_log.py — Native Google Docs append/read for the Jarvis Dev Log.

Stops the "new doc every session" problem: Jarvis appends entries directly
to the shared doc (ID stored in config.json) so Jack and Oliver get a single
running log readable by voice.

Doc layout expected:
  ... header content ...
  ## LOG
  ---
  ### YYYY-MM-DD HH:MM | {author}
  - entry line
  ---
  ... older entries ...

Tools:
  read_dev_log()                        READ_ONLY
  get_dev_log_summary()                 READ_ONLY  (last 3 entries)
  append_dev_log_entry(summary, author) MODERATE

Requires Google OAuth with 'https://www.googleapis.com/auth/documents' scope.
If the token predates the Docs scope being added, delete memory/google_token.json
and restart Jarvis once to re-authorise.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

logger = logging.getLogger("jarvis.tools.dev_log")

_LOG_SECTION_MARKER = "## LOG"
_ENTRY_SEPARATOR = "---"
_DEFAULT_DOC_ID = "18OUXDja6GbV99dB_sv2iGlsLJTCqg3AQ95kvQbazQyc"
_DEFAULT_AUTHOR = "Jack's Claude"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _doc_id() -> str:
    try:
        from config import Config
        cfg = Config.load()
        return (getattr(cfg, "dev_log_doc_id", "") or _DEFAULT_DOC_ID).strip()
    except Exception:  # noqa: BLE001
        return _DEFAULT_DOC_ID


def _author() -> str:
    try:
        from config import Config
        cfg = Config.load()
        return (getattr(cfg, "dev_log_author", "") or _DEFAULT_AUTHOR).strip()
    except Exception:  # noqa: BLE001
        return _DEFAULT_AUTHOR


def _get_docs_service():
    from tools.google_auth import get_google_service
    return get_google_service("docs", "v1")


def _missing_doc_id_message() -> str:
    return (
        "Dev Log not configured. Set dev_log_doc_id in config.json "
        "(Hub → Settings) or it defaults to the shared sprint doc."
    )


def _extract_text(doc: dict) -> str:
    """Pull plain text from a Google Docs document dict."""
    lines: list[str] = []
    for block in (doc.get("body") or {}).get("content") or []:
        para = block.get("paragraph") or {}
        for elem in para.get("elements") or []:
            run = elem.get("textRun") or {}
            content = run.get("content") or ""
            if content:
                lines.append(content)
    return "".join(lines)


def _find_log_section_index(doc: dict) -> int | None:
    """Return the character offset of the first character AFTER '## LOG\\n---\\n'.

    Returns None if the LOG section marker is not found.
    """
    text = _extract_text(doc)
    marker = _LOG_SECTION_MARKER
    pos = text.find(marker)
    if pos == -1:
        return None
    # Skip past the marker line and the separator line that follows it.
    after_marker = text.find("\n", pos)
    if after_marker == -1:
        return pos + len(marker)
    after_marker += 1  # move past the newline
    if text[after_marker:after_marker + len(_ENTRY_SEPARATOR)] == _ENTRY_SEPARATOR:
        after_sep = text.find("\n", after_marker)
        if after_sep != -1:
            return after_sep + 1
        return after_marker + len(_ENTRY_SEPARATOR)
    return after_marker


def _split_entries(text: str) -> list[str]:
    """Split the text of the log section into individual entry blocks."""
    # Find start of LOG section
    marker_pos = text.find(_LOG_SECTION_MARKER)
    if marker_pos == -1:
        log_text = text
    else:
        log_text = text[marker_pos + len(_LOG_SECTION_MARKER):]

    # Split on separator lines
    parts = re.split(r"\n---\n?", log_text)
    entries = []
    for part in parts:
        stripped = part.strip()
        if stripped and stripped != _LOG_SECTION_MARKER.strip():
            entries.append(stripped)
    return entries


def _build_entry_text(summary: str, author: str, timestamp: str) -> str:
    """Format a log entry in the canonical style."""
    header = f"### {timestamp} | {author}\n"
    lines = []
    for line in (summary or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            lines.append(stripped)
        else:
            lines.append(f"- {stripped}")
    body = "\n".join(lines) + "\n" if lines else ""
    return f"{header}{body}{_ENTRY_SEPARATOR}\n"


# ---------------------------------------------------------------------------
# Public tools
# ---------------------------------------------------------------------------

def read_dev_log() -> str:
    """Return the full text of the Jarvis Dev Log Google Doc."""
    doc_id = _doc_id()
    if not doc_id:
        return _missing_doc_id_message()
    try:
        svc = _get_docs_service()
        doc = svc.documents().get(documentId=doc_id).execute()
        text = _extract_text(doc)
        return text.strip() or "Dev Log is empty."
    except Exception as exc:  # noqa: BLE001
        logger.debug("read_dev_log failed: %s", exc, exc_info=True)
        return f"Could not read Dev Log: {exc}"


def get_dev_log_summary() -> str:
    """Return the last three entries from the Jarvis Dev Log (newest first)."""
    doc_id = _doc_id()
    if not doc_id:
        return _missing_doc_id_message()
    try:
        svc = _get_docs_service()
        doc = svc.documents().get(documentId=doc_id).execute()
        text = _extract_text(doc)
        entries = _split_entries(text)
        # Entries are newest-first (we insert at the top); take first three.
        recent = entries[:3]
        if not recent:
            return "Dev Log has no entries yet."
        return ("\n---\n").join(recent) + "\n---"
    except Exception as exc:  # noqa: BLE001
        logger.debug("get_dev_log_summary failed: %s", exc, exc_info=True)
        return f"Could not read Dev Log summary: {exc}"


def append_dev_log_entry(summary: str, author: str = "") -> str:
    """Append a new entry to the top of the LOG section in the Dev Log doc.

    Args:
        summary: One or more lines describing what happened. Each line becomes
                 a bullet point. Lines already starting with '- ' are kept as-is.
        author:  Name shown in the entry header. Defaults to config dev_log_author.

    Returns a confirmation string with the timestamp, or an error message.
    """
    doc_id = _doc_id()
    if not doc_id:
        return _missing_doc_id_message()

    resolved_author = author.strip() if author.strip() else _author()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry_text = _build_entry_text(summary, resolved_author, timestamp)

    try:
        svc = _get_docs_service()
        doc = svc.documents().get(documentId=doc_id).execute()
        insert_index = _find_log_section_index(doc)
        if insert_index is None:
            return (
                "Could not find '## LOG' section in the Dev Log doc. "
                "Make sure the doc contains that heading."
            )

        svc.documents().batchUpdate(
            documentId=doc_id,
            body={
                "requests": [
                    {
                        "insertText": {
                            "location": {"index": insert_index},
                            "text": entry_text,
                        }
                    }
                ]
            },
        ).execute()

        logger.info("📓 Dev Log updated: %s | %s", timestamp, resolved_author)
        return f"Dev Log updated at {timestamp} by {resolved_author}."
    except Exception as exc:  # noqa: BLE001
        logger.debug("append_dev_log_entry failed: %s", exc, exc_info=True)
        return f"Could not update Dev Log: {exc}"
