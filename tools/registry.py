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
from tools.device_control import (
    get_battery_status,
    get_system_info,
    lock_screen,
    set_appearance_mode,
    set_brightness,
    set_do_not_disturb,
    set_mute,
    set_screen_saver,
    set_volume,
    set_wifi,
)
from tools.download import download_file
from tools.login_item import disable_login_item, enable_login_item, is_login_item_enabled
from tools.media import (
    find_and_open_file,
    find_file,
    get_recent_files,
    open_desktop,
    open_downloads,
    open_file,
    open_photos,
    open_podcasts,
)
from tools.music import (
    get_now_playing,
    pause as music_pause,
    play as music_play,
    previous as music_previous,
    search_and_play,
    set_volume as music_set_volume,
    skip as music_skip,
)
from tools.pitch_deck import create_pitch_deck
from memory.semantic import remember as remember_fact, search as search_memory_index
from memory.variables import get_variable, set_variable
from tools.github import create_github_comment, get_github_repo_summary, search_github_issues
from tools.google_calendar import get_calendar_events, get_todays_schedule
from tools.google_contacts import list_contacts, search_contacts
from tools.google_drive import read_drive_file, search_drive
from tools.google_gmail import get_unread_emails, list_recent_emails, search_emails, send_email
from tools.google_sheets import append_row, read_sheet, update_cell
from tools.slack import read_slack_channel, send_slack_message
from tools.system import open_app
from tools.time_date import get_current_time
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
        "name": "get_current_time",
        "description": (
            "Get the current date, time, day of week, and timezone. Call this whenever "
            "the user asks what time or date it is, or when you need to know 'now' for "
            "calendar or scheduling context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": (
                        "IANA timezone name (e.g. 'America/Los_Angeles'). "
                        "Leave empty for system local time."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "set_volume",
        "description": "Set the system master volume to a percentage (0–100).",
        "input_schema": {
            "type": "object",
            "properties": {
                "level": {"type": "integer", "description": "Volume percent, 0–100."},
            },
            "required": ["level"],
        },
    },
    {
        "name": "set_mute",
        "description": "Mute or unmute the system audio.",
        "input_schema": {
            "type": "object",
            "properties": {
                "muted": {"type": "boolean", "description": "True to mute, false to unmute."},
            },
            "required": ["muted"],
        },
    },
    {
        "name": "set_brightness",
        "description": "Set the main display brightness to a percentage (0–100). Laptop displays only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "level": {"type": "integer", "description": "Brightness percent, 0–100."},
            },
            "required": ["level"],
        },
    },
    {
        "name": "set_do_not_disturb",
        "description": "Turn Do Not Disturb on or off (suppresses notifications on Windows).",
        "input_schema": {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean", "description": "True for DND on, false for off."},
            },
            "required": ["enabled"],
        },
    },
    {
        "name": "lock_screen",
        "description": "Lock the computer / workstation immediately.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_battery_status",
        "description": "Get the current battery percentage and whether the Mac is charging.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_system_info",
        "description": "Get Mac system information: macOS version, chip type, and RAM.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "set_appearance_mode",
        "description": "Switch macOS between dark mode and light mode.",
        "input_schema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "description": "'dark' or 'light'"},
            },
            "required": ["mode"],
        },
    },
    {
        "name": "set_wifi",
        "description": "Turn WiFi on or off.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "'on' or 'off'"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "set_screen_saver",
        "description": "Start the macOS screen saver.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "'start'"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "enable_login_item",
        "description": "Enable Launch at login on macOS so Jarvis starts automatically when you log in.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "disable_login_item",
        "description": "Disable Launch at login on macOS so Jarvis no longer starts automatically.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "music_play",
        "description": "Start or resume playback in the macOS Music app.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "music_pause",
        "description": "Pause playback in the macOS Music app.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "music_skip",
        "description": "Skip to the next track in the macOS Music app.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "music_previous",
        "description": "Go to the previous track in the macOS Music app.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "music_set_volume",
        "description": "Set Music.app playback volume (0–100). This is not system master volume.",
        "input_schema": {
            "type": "object",
            "properties": {
                "level": {"type": "integer", "description": "Volume percent, 0–100."},
            },
            "required": ["level"],
        },
    },
    {
        "name": "get_now_playing",
        "description": "Get the currently playing song from Music.app (title, artist, album, state).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "search_and_play",
        "description": (
            "Search for a song and play the top match in Music.app (macOS). "
            "On Windows, opens a Spotify search for the query."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Song, artist, or album to search for."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "find_file",
        "description": "Search for files on the user's Mac using Spotlight. Returns top 5 matches with file paths.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "File name or keyword to search for"},
                "file_type": {
                    "type": "string",
                    "description": "Optional: 'pdf', 'image', 'video', 'presentation', 'doc'",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "find_and_open_file",
        "description": "Find a file by name and immediately open it in its default app.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "File name to find and open"},
                "file_type": {"type": "string", "description": "Optional file type filter"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "open_photos",
        "description": "Open the macOS Photos app.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Optional search term"},
            },
            "required": [],
        },
    },
    {
        "name": "open_podcasts",
        "description": "Open the macOS Podcasts app.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Optional podcast name"},
            },
            "required": [],
        },
    },
    {
        "name": "get_recent_files",
        "description": "Get a list of recently used files from the past 7 days.",
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "description": "Number of files to return (default 10)"},
            },
            "required": [],
        },
    },
    {
        "name": "open_downloads",
        "description": "Open the Downloads folder in Finder.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "open_desktop",
        "description": "Open the Desktop folder in Finder.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "open_file",
        "description": "Open a specific file path in its default application.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute path to the file"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "create_pitch_deck",
        "description": (
            "Generate a PowerPoint pitch deck on any topic. Claude writes the content, "
            "saves a .pptx file to Downloads, and opens it automatically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The topic or title of the pitch deck",
                },
                "slide_count": {
                    "type": "integer",
                    "description": "Number of slides (default 5, max 15)",
                },
                "style": {
                    "type": "string",
                    "description": "Visual style: 'professional' (dark), 'light', or 'bold'",
                },
            },
            "required": ["topic"],
        },
    },
    {
        "name": "download_file",
        "description": (
            "Download a file from an http(s) URL to the user's Downloads folder. "
            "Requires user confirmation. Validates the URL and caps the size at 100 MB."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The http(s) URL to download."},
                "filename": {
                    "type": "string",
                    "description": "Optional name to save as; otherwise inferred from the URL.",
                },
            },
            "required": ["url"],
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
        "name": "escalate",
        "description": (
            "Hand this turn off to the more capable model. Call this FIRST — before "
            "answering or using other tools — when the request needs careful multi-step "
            "reasoning, planning, analysis, coding, or nuanced writing that a fast model "
            "might get wrong. Do NOT call it for simple lookups, chit-chat, or single "
            "tool actions; answer those directly."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
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
        "name": "list_recent_emails",
        "description": "Summarise the most recent Gmail inbox messages (sender, subject, snippet).",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_results": {
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
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (default 5, max 20).",
                },
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
    "get_current_time": lambda **kw: get_current_time(kw.get("timezone", "")),
    "web_search": lambda **kw: web_search(kw["query"]),
    "download_file": lambda **kw: download_file(kw["url"], kw.get("filename")),
    "set_volume": lambda **kw: set_volume(kw["level"]),
    "set_mute": lambda **kw: set_mute(bool(kw["muted"])),
    "set_brightness": lambda **kw: set_brightness(kw["level"]),
    "set_do_not_disturb": lambda **kw: set_do_not_disturb(bool(kw["enabled"])),
    "lock_screen": lambda **kw: lock_screen(),
    "get_battery_status": lambda **kw: get_battery_status(),
    "get_system_info": lambda **kw: get_system_info(),
    "set_appearance_mode": lambda **kw: set_appearance_mode(kw["mode"]),
    "set_wifi": lambda **kw: set_wifi(kw["action"]),
    "set_screen_saver": lambda **kw: set_screen_saver(kw.get("action", "start")),
    "enable_login_item": lambda **kw: enable_login_item(),
    "disable_login_item": lambda **kw: disable_login_item(),
    "music_play": lambda **kw: music_play(),
    "music_pause": lambda **kw: music_pause(),
    "music_skip": lambda **kw: music_skip(),
    "music_previous": lambda **kw: music_previous(),
    "music_set_volume": lambda **kw: music_set_volume(int(kw["level"])),
    "get_now_playing": lambda **kw: get_now_playing(),
    "search_and_play": lambda **kw: search_and_play(kw["query"]),
    "find_file": lambda **kw: find_file(kw["query"], kw.get("file_type", "")),
    "find_and_open_file": lambda **kw: find_and_open_file(kw["query"], kw.get("file_type", "")),
    "open_photos": lambda **kw: open_photos(kw.get("query", "")),
    "open_podcasts": lambda **kw: open_podcasts(kw.get("query", "")),
    "get_recent_files": lambda **kw: get_recent_files(int(kw.get("count") or 10)),
    "open_downloads": lambda **kw: open_downloads(),
    "open_desktop": lambda **kw: open_desktop(),
    "open_file": lambda **kw: open_file(kw["file_path"]),
    "create_pitch_deck": lambda **kw: create_pitch_deck(
        kw["topic"],
        int(kw.get("slide_count") or 5),
        kw.get("style", "professional"),
        kw.get("output_dir", ""),
    ),
    "set_variable": lambda **kw: (set_variable(kw["key"], kw["value"]) or f"Saved {kw['key']}={kw['value']}"),
    "get_variable": lambda **kw: (get_variable(kw["key"]) or f"No value stored for '{kw['key']}'."),
    "write_note": lambda **kw: write_note(kw["title"], kw["content"]),
    "read_note": lambda **kw: (read_note(kw["title"]) or f"No note found for '{kw['title']}'."),
    "remember": lambda **kw: remember_fact(kw["fact"]),
    "escalate": lambda **kw: "Escalated to the advanced model.",
    "search_memory": lambda **kw: _format_memory_hits(
        search_memory_index(kw["query"], top_k=int(kw.get("limit") or 5))
    ),
    "get_calendar_events": lambda **kw: get_calendar_events(kw.get("days", 7)),
    "get_todays_schedule": lambda **kw: get_todays_schedule(),
    "get_unread_emails": lambda **kw: get_unread_emails(kw.get("max", 5)),
    "list_recent_emails": lambda **kw: list_recent_emails(kw.get("max_results", 5)),
    "search_emails": lambda **kw: search_emails(
        kw["query"], kw.get("max_results", 5),
    ),
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
    "get_current_time",
    "web_search",
    "get_weather",
    "get_calendar_events",
    "get_todays_schedule",
    "get_unread_emails",
    "list_recent_emails",
    "search_emails",
    "read_sheet",
    "search_contacts",
    "list_contacts",
    "search_drive",
    "read_drive_file",
    "read_slack_channel",
    "search_github_issues",
    "get_github_repo_summary",
    "get_battery_status",
    "get_system_info",
    "find_file",
    "get_recent_files",
    "open_downloads",
    "open_desktop",
})

# Low-risk mutating tools — auto-allow in voice mode (confirm gate does not apply).
AUTO_ALLOW_TOOLS = frozenset({
    "open_app",
    "set_volume",
    "set_mute",
    "set_brightness",
    "set_do_not_disturb",
    "lock_screen",
    "set_appearance_mode",
    "set_screen_saver",
    "set_wifi",
    "open_photos",
    "open_podcasts",
    "find_and_open_file",
    "open_file",
    "set_variable",
    "write_note",
    "remember",
    "escalate",
})

# Moderate-risk tools — dashboard confirm in voice mode when confirm_before_execute is on.
MODERATE_TOOLS = frozenset({
    "enable_login_item",
    "disable_login_item",
    "music_play",
    "music_pause",
    "music_skip",
    "music_previous",
    "music_set_volume",
    "get_now_playing",
    "search_and_play",
})

# High-risk mutating tools — dashboard confirm required when confirm_before_execute is on.
CONFIRM_REQUIRED_TOOLS = frozenset({
    "download_file",
    "send_email",
    "append_row",
    "update_cell",
    "send_slack_message",
    "create_github_comment",
    "create_pitch_deck",
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

    if confirm and name in (CONFIRM_REQUIRED_TOOLS | MODERATE_TOOLS):
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
