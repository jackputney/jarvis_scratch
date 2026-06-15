"""
tools/registry.py — Central registry of all Jarvis tools.

Holds two things:
  1. TOOL_DEFINITIONS  — the Anthropic-format tool specs passed to Claude via tools=.
  2. TOOL_DISPATCH     — a plain dict mapping tool name → Python callable.

Adding a new tool means adding one entry in each dict. No decorator magic, no
class hierarchy — just explicit, readable mappings.
"""

from __future__ import annotations

from memory.knowledge import read_note, write_note
from memory.semantic import remember as remember_fact, search as search_memory_index
from memory.variables import get_variable, set_variable
from tools.github import create_github_comment, get_github_repo_summary, search_github_issues
from tools.google_calendar import get_calendar_events, get_todays_schedule
from tools.google_contacts import list_contacts, search_contacts
from tools.google_drive import read_drive_file, search_drive
from tools.gmail import get_unread_emails, search_emails, send_email
from tools.google_sheets import append_row, read_sheet, update_cell
from tools.slack import read_slack_channel, send_slack_message
from tools.system import open_app
from tools.weather import get_weather
from tools.web import web_search

# ---------------------------------------------------------------------------
# Anthropic tool definitions — passed verbatim as the tools= parameter.
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "open_app",
        "description": "Open an application by name (macOS, Windows, or Linux).",
        "input_schema": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "The application name as it appears in /Applications, e.g. 'Safari'.",
                },
            },
            "required": ["app_name"],
        },
    },
    {
        "name": "web_search",
        "description": "Search the web via Brave Search (or DuckDuckGo fallback) and return ranked results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "set_variable",
        "description": "Persist a personal fact about the user as a key-value pair (e.g. home_city='London').",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The variable name."},
                "value": {"type": "string", "description": "The value to store."},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "get_variable",
        "description": "Retrieve a stored personal fact by key.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The variable name to look up."},
            },
            "required": ["key"],
        },
    },
    {
        "name": "write_note",
        "description": "Save a Markdown note on a topic. Creates or overwrites the note for that title.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short descriptive title for the note."},
                "content": {"type": "string", "description": "Markdown body of the note."},
            },
            "required": ["title", "content"],
        },
    },
    {
        "name": "read_note",
        "description": "Read an existing Markdown note by title.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "The note title to retrieve."},
            },
            "required": ["title"],
        },
    },
    {
        "name": "remember",
        "description": (
            "Persist a durable personal fact about the user to their local profile "
            "(preferences, relationships, routines, goals). Use for information worth "
            "recalling in future conversations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fact": {"type": "string", "description": "The fact to remember about the user."},
            },
            "required": ["fact"],
        },
    },
    {
        "name": "search_memory",
        "description": "Search the user's local semantic memory for relevant past notes and diary entries.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for in memory."},
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 5).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_calendar_events",
        "description": "List upcoming Google Calendar events (title, time, location, attendees).",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days ahead to fetch (default 7, max 30).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_todays_schedule",
        "description": "Get today's calendar events formatted for speaking aloud.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_unread_emails",
        "description": "Summarise unread Gmail inbox messages (sender, subject, snippet).",
        "input_schema": {
            "type": "object",
            "properties": {
                "max": {
                    "type": "integer",
                    "description": "Maximum number of emails to return (default 5, max 20).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "search_emails",
        "description": "Search Gmail using standard Gmail query syntax.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Gmail search query."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "send_email",
        "description": "Send a plain-text email via Gmail. Requires user confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address."},
                "subject": {"type": "string", "description": "Email subject line."},
                "body": {"type": "string", "description": "Plain-text email body."},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "read_sheet",
        "description": "Read a Google Sheets cell range and return a plain-text table.",
        "input_schema": {
            "type": "object",
            "properties": {
                "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID from the sheet URL."},
                "range": {
                    "type": "string",
                    "description": "A1 notation range, e.g. 'Sheet1!A1:D10'.",
                },
            },
            "required": ["spreadsheet_id", "range"],
        },
    },
    {
        "name": "append_row",
        "description": "Append a row of values to a Google Sheet. Requires user confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID."},
                "sheet_name": {"type": "string", "description": "Tab name, e.g. 'Sheet1'."},
                "values": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Cell values for the new row.",
                },
            },
            "required": ["spreadsheet_id", "sheet_name", "values"],
        },
    },
    {
        "name": "update_cell",
        "description": "Update a single Google Sheets cell. Requires user confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID."},
                "cell": {
                    "type": "string",
                    "description": "A1 notation cell, e.g. 'Sheet1!C5'.",
                },
                "value": {"type": "string", "description": "New cell value."},
            },
            "required": ["spreadsheet_id", "cell", "value"],
        },
    },
    {
        "name": "get_weather",
        "description": "Get current weather and a 3-day forecast for a location (Open-Meteo, no API key).",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name or 'City, Country'."},
            },
            "required": ["location"],
        },
    },
    {
        "name": "search_contacts",
        "description": "Search Google Contacts by name and return matching people with email and phone.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Name or partial name to search for."},
                "max_results": {"type": "integer", "description": "Maximum matches (default 5)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_contacts",
        "description": "List recent Google Contacts with email and phone.",
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "description": "Number of contacts (default 10, max 50)."},
            },
            "required": [],
        },
    },
    {
        "name": "search_drive",
        "description": "Search Google Drive files by name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term for file names."},
                "max_results": {"type": "integer", "description": "Maximum results (default 5)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_drive_file",
        "description": "Read a Google Drive file's text content by file ID (text exports only, truncated at 5000 chars).",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "Drive file ID from search results."},
            },
            "required": ["file_id"],
        },
    },
    {
        "name": "send_slack_message",
        "description": "Send a message to a Slack channel. Requires user confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel name or ID."},
                "text": {"type": "string", "description": "Message text to send."},
            },
            "required": ["channel", "text"],
        },
    },
    {
        "name": "read_slack_channel",
        "description": "Read recent messages from a Slack channel.",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel name or ID."},
                "count": {"type": "integer", "description": "Number of messages (default 10)."},
            },
            "required": ["channel"],
        },
    },
    {
        "name": "search_github_issues",
        "description": "Search open or closed issues in a GitHub repository.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository as owner/name."},
                "query": {"type": "string", "description": "Optional search filter."},
                "state": {"type": "string", "description": "open, closed, or all (default open)."},
            },
            "required": ["repo"],
        },
    },
    {
        "name": "get_github_repo_summary",
        "description": "Get basic stats and description for a GitHub repository.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository as owner/name."},
            },
            "required": ["repo"],
        },
    },
    {
        "name": "create_github_comment",
        "description": "Add a comment to a GitHub issue. Requires user confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository as owner/name."},
                "issue_number": {"type": "integer", "description": "Issue number."},
                "body": {"type": "string", "description": "Comment body."},
            },
            "required": ["repo", "issue_number", "body"],
        },
    },
]

# ---------------------------------------------------------------------------
# Dispatch table — maps tool name → callable.
# All callables accept **kwargs matching the tool's input_schema properties.
# ---------------------------------------------------------------------------

TOOL_DISPATCH: dict[str, callable] = {
    "open_app": lambda **kw: open_app(kw["app_name"]),
    "web_search": lambda **kw: web_search(kw["query"]),
    "set_variable": lambda **kw: (set_variable(kw["key"], kw["value"]) or f"Saved {kw['key']}={kw['value']}"),
    "get_variable": lambda **kw: (get_variable(kw["key"]) or f"No value stored for '{kw['key']}'."),
    "write_note": lambda **kw: write_note(kw["title"], kw["content"]),
    "read_note": lambda **kw: (read_note(kw["title"]) or f"No note found for '{kw['title']}'."),
    "remember": lambda **kw: remember_fact(kw["fact"]),
    "search_memory": lambda **kw: _format_memory_hits(
        search_memory_index(kw["query"], top_k=int(kw.get("limit") or 5))
    ),
    "get_calendar_events": lambda **kw: get_calendar_events(kw.get("days", 7)),
    "get_todays_schedule": lambda **kw: get_todays_schedule(),
    "get_unread_emails": lambda **kw: get_unread_emails(kw.get("max", 5)),
    "search_emails": lambda **kw: search_emails(kw["query"]),
    "send_email": lambda **kw: send_email(kw["to"], kw["subject"], kw["body"]),
    "read_sheet": lambda **kw: read_sheet(kw["spreadsheet_id"], kw["range"]),
    "append_row": lambda **kw: append_row(kw["spreadsheet_id"], kw["sheet_name"], kw["values"]),
    "update_cell": lambda **kw: update_cell(kw["spreadsheet_id"], kw["cell"], kw["value"]),
    "get_weather": lambda **kw: get_weather(kw["location"]),
    "search_contacts": lambda **kw: search_contacts(kw["query"], int(kw.get("max_results") or 5)),
    "list_contacts": lambda **kw: list_contacts(int(kw.get("count") or 10)),
    "search_drive": lambda **kw: search_drive(kw["query"], int(kw.get("max_results") or 5)),
    "read_drive_file": lambda **kw: read_drive_file(kw["file_id"]),
    "send_slack_message": lambda **kw: send_slack_message(kw["channel"], kw["text"]),
    "read_slack_channel": lambda **kw: read_slack_channel(kw["channel"], int(kw.get("count") or 10)),
    "search_github_issues": lambda **kw: search_github_issues(
        kw["repo"], kw.get("query", ""), kw.get("state", "open"),
    ),
    "get_github_repo_summary": lambda **kw: get_github_repo_summary(kw["repo"]),
    "create_github_comment": lambda **kw: create_github_comment(
        kw["repo"], int(kw["issue_number"]), kw["body"],
    ),
}

# Read-only tools — never confirm.
READ_ONLY_TOOLS = frozenset({
    "get_variable",
    "read_note",
    "search_memory",
    "web_search",
    "get_weather",
    "get_calendar_events",
    "get_todays_schedule",
    "get_unread_emails",
    "search_emails",
    "read_sheet",
    "search_contacts",
    "list_contacts",
    "search_drive",
    "read_drive_file",
    "read_slack_channel",
    "search_github_issues",
    "get_github_repo_summary",
})

# Low-risk mutating tools — auto-allow in voice mode (confirm gate does not apply).
AUTO_ALLOW_TOOLS = frozenset({
    "open_app",
    "set_variable",
    "write_note",
    "remember",
})

# High-risk mutating tools — dashboard confirm required when confirm_before_execute is on.
CONFIRM_REQUIRED_TOOLS = frozenset({
    "send_email",
    "append_row",
    "update_cell",
    "send_slack_message",
    "create_github_comment",
})


def _format_memory_hits(hits: list[dict]) -> str:
    if not hits:
        return "No matching memories found."
    lines = []
    for hit in hits:
        lines.append(f"[{hit['source']}] {hit['chunk']}")
    return "\n\n".join(lines)


def dispatch_tool(
    name: str,
    inputs: dict,
    confirm: bool = False,
    confirm_timeout_sec: int = 30,
    cancel_check: callable | None = None,
) -> str:
    """Execute a tool by name with the given inputs dict.

    When confirm=True, high-risk tools wait for dashboard Allow/Deny (with timeout).
    Low-risk mutating tools and all read-only tools run immediately.

    Returns the tool result as a plain string, or an error message if the tool
    name is not registered or confirmation was denied.
    """
    if name not in TOOL_DISPATCH:
        return f"Unknown tool: {name}"

    if confirm and name in CONFIRM_REQUIRED_TOOLS:
        from tools import confirm as confirm_mod

        decision = confirm_mod.wait_for_confirm(
            name,
            inputs,
            timeout_sec=confirm_timeout_sec,
            cancel_check=cancel_check,
        )
        if decision == "allow":
            pass
        elif decision == "timeout":
            return f"Tool '{name}' not executed: confirmation timed out after {confirm_timeout_sec}s."
        elif decision == "cancel":
            return f"Tool '{name}' not executed: cancelled."
        else:
            return f"Tool '{name}' not executed: denied."

    try:
        result = TOOL_DISPATCH[name](**inputs)
        return str(result) if result is not None else "Done."
    except Exception as exc:
        return f"Tool error ({name}): {exc}"
