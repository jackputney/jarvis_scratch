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
from tools.download import download_file
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
from tools.clipboard import read_clipboard, write_clipboard
from tools.login_item import disable_login_item, enable_login_item, is_login_item_enabled, manage_startup
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
from tools.media_control import media_control
from tools.music import (
    get_now_playing,
    pause as music_pause,
    play as music_play,
    previous as music_previous,
    search_and_play,
    set_volume as music_set_volume,
    skip as music_skip,
)
from tools.phone import end_call, get_call_status, make_call
from tools.pitch_deck import create_pitch_deck
from tools.system_info import active_window, list_processes, system_info as pc_system_info
from memory.semantic import remember as remember_fact, search as search_memory_index
from memory.variables import get_variable, set_variable
from tools.github import create_github_comment, get_github_repo_summary, search_github_issues
from tools.github_self import (
    comment_own_issue,
    create_own_branch,
    create_own_file,
    create_own_issue,
    create_own_pr,
    get_own_commits,
    get_own_issues,
    list_own_files,
    read_own_file,
    search_own_code,
)
from tools.dev_log import append_dev_log_entry, get_dev_log_summary, read_dev_log
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
from updater import apply_update, check_and_prompt_update, check_for_updates, restart_jarvis

# ---------------------------------------------------------------------------
# Anthropic tool definitions — passed verbatim as the tools= parameter.
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "open_app",
        "description": (
            "Open or launch a desktop application by name (macOS, Windows, or Linux). "
            "Call this whenever the user asks to open, launch, or start an app — e.g. Spotify, "
            "Chrome, Notepad, Safari. Never tell the user an app is not installed without "
            "calling this tool first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": (
                        "Application name as shown in the Start menu or launcher — "
                        "e.g. 'Spotify', 'Chrome', 'Notepad', 'Safari'."
                    ),
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
        "name": "manage_startup",
        "description": (
            "Enable, disable, or check Jarvis launch-at-login status. macOS uses LaunchAgent; "
            "Windows uses Task Scheduler to run run.ps1 at user logon."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "One of: enable, disable, status.",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "music_play",
        "description": (
            "Start or resume playback in the macOS Music app. macOS only — on Windows Jarvis "
            "cannot control playback; use search_and_play or open_app to open Spotify instead."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "music_pause",
        "description": (
            "Pause playback in the macOS Music app. macOS only — on Windows Jarvis cannot "
            "control playback."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "music_skip",
        "description": (
            "Skip to the next track in the macOS Music app. macOS only — on Windows Jarvis "
            "cannot control playback."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "music_previous",
        "description": (
            "Go to the previous track in the macOS Music app. macOS only — on Windows Jarvis "
            "cannot control playback."
        ),
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
        "description": (
            "Get the currently playing song from macOS Music.app (title, artist, album, state). "
            "macOS only — on Windows playback state is not available."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "search_and_play",
        "description": (
            "Search for a song and play the top match in macOS Music.app. macOS only for playback. "
            "On Windows: opens a Spotify search URI only (cannot play/pause/skip); tell the user "
            "to press play in Spotify. Also use open_app for Spotify."
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
        "name": "media_control",
        "description": (
            "Control media playback globally on Windows using system media keys. Works with whatever "
            "app has media focus (Spotify, YouTube in browser, etc.). Actions: play, pause, "
            "play_pause, skip, next, previous, prev."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "play, pause, play_pause, skip, next, previous, or prev.",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "system_info",
        "description": "Get local CPU, RAM, and disk usage percentages.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_processes",
        "description": "List the top 20 running processes sorted by CPU usage.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "active_window",
        "description": "Get the title of the currently focused window (Windows).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_clipboard",
        "description": "Read plain text from the system clipboard (Windows).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "write_clipboard",
        "description": "Write plain text to the system clipboard (Windows).",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to copy to the clipboard."},
            },
            "required": ["text"],
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
        "description": "Open the Photos app (macOS only).",
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
        "description": "Open the Podcasts app (macOS only).",
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
        "description": "Send a plain-text email via Gmail. The user gives only a recipient and the gist — infer a short subject yourself and draft the body from their intent. Never ask the user for a subject line or to dictate the body verbatim. Call this tool immediately when asked to send mail; do not ask for confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address."},
                "subject": {"type": "string", "description": "Email subject line."},
                "body": {"type": "string", "description": "Plain-text email body."},
            },
            "required": ["to"],
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
    {
        "name": "read_own_file",
        "description": "Read a source file from Jarvis's own GitHub repo (read-only).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repo-relative file path, e.g. tools/web.py."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_own_files",
        "description": "List file paths in a directory of Jarvis's own GitHub repo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "Repo-relative directory (empty for repo root)."},
            },
            "required": [],
        },
    },
    {
        "name": "search_own_code",
        "description": "Search code in Jarvis's own GitHub repository.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Code search query."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_own_commits",
        "description": "Recent commits on Jarvis's own repo main branch.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of commits (default 10, max 30)."},
            },
            "required": [],
        },
    },
    {
        "name": "get_own_issues",
        "description": "List open or closed issues on Jarvis's own GitHub repo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "state": {"type": "string", "description": "open, closed, or all (default open)."},
            },
            "required": [],
        },
    },
    {
        "name": "create_own_branch",
        "description": "Create a new branch in Jarvis's own GitHub repo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "branch_name": {"type": "string", "description": "New branch name."},
                "from_branch": {"type": "string", "description": "Base branch (default main)."},
            },
            "required": ["branch_name"],
        },
    },
    {
        "name": "create_own_file",
        "description": "Create or update a file in Jarvis's own GitHub repo. Requires confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repo-relative file path."},
                "content": {"type": "string", "description": "Full file contents."},
                "message": {"type": "string", "description": "Commit message."},
                "branch": {"type": "string", "description": "Target branch (default main)."},
            },
            "required": ["path", "content", "message"],
        },
    },
    {
        "name": "create_own_pr",
        "description": "Open a pull request on Jarvis's own GitHub repo. Requires confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "PR title."},
                "body": {"type": "string", "description": "PR description."},
                "head": {"type": "string", "description": "Head branch with changes."},
                "base": {"type": "string", "description": "Base branch (default main)."},
            },
            "required": ["title", "body", "head"],
        },
    },
    {
        "name": "create_own_issue",
        "description": "Create a GitHub issue on Jarvis's own repo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Issue title."},
                "body": {"type": "string", "description": "Issue body."},
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional label names.",
                },
            },
            "required": ["title", "body"],
        },
    },
    {
        "name": "comment_own_issue",
        "description": "Post a comment on an issue in Jarvis's own GitHub repo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_number": {"type": "integer", "description": "Issue number."},
                "body": {"type": "string", "description": "Comment text."},
            },
            "required": ["issue_number", "body"],
        },
    },
    {
        "name": "check_for_updates",
        "description": (
            "Check if a newer version of Jarvis is available on GitHub. "
            "Returns a spoken summary like 'An update is available with 3 new commits'."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "apply_update",
        "description": (
            "Download and install the latest Jarvis update from GitHub (fast-forward only — "
            "will not overwrite local changes). Returns success/failure."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "restart_jarvis",
        "description": "Restart Jarvis to apply an update or recover from errors.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_dev_log",
        "description": "Read the full Jarvis Dev Log Google Doc — session history for Jack and Oliver.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_dev_log_summary",
        "description": "Return the last 3 entries from the Jarvis Dev Log. Use for 'what did Oliver build today' or 'what happened recently' queries.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "append_dev_log_entry",
        "description": "Append a new entry to the Jarvis Dev Log Google Doc. Use after sessions, reflections, or when the user says 'log this session' or 'update the dev log'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "One or more lines describing what happened. Each line becomes a bullet point.",
                },
                "author": {
                    "type": "string",
                    "description": "Entry author name. Defaults to config dev_log_author.",
                },
            },
            "required": ["summary"],
        },
    },
    {
        "name": "make_call",
        "description": (
            "Place an outbound phone call via Twilio. The recipient number must be "
            "E.164 format (e.g. +14155551234). Requires user confirmation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient phone number in E.164 format."},
                "purpose": {
                    "type": "string",
                    "description": "Optional reason for the call (logged for context).",
                },
            },
            "required": ["to"],
        },
    },
    {
        "name": "end_call",
        "description": "Hang up an active Twilio phone call.",
        "input_schema": {
            "type": "object",
            "properties": {
                "call_sid": {
                    "type": "string",
                    "description": "Twilio Call SID. Leave empty to end the most recent call.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_call_status",
        "description": "Get the current status of a Twilio phone call (ringing, in-progress, completed, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "call_sid": {
                    "type": "string",
                    "description": "Twilio Call SID. Leave empty for the most recent call.",
                },
            },
            "required": [],
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
    "manage_startup": lambda **kw: manage_startup(kw["action"]),
    "music_play": lambda **kw: music_play(),
    "music_pause": lambda **kw: music_pause(),
    "music_skip": lambda **kw: music_skip(),
    "music_previous": lambda **kw: music_previous(),
    "music_set_volume": lambda **kw: music_set_volume(int(kw["level"])),
    "get_now_playing": lambda **kw: get_now_playing(),
    "search_and_play": lambda **kw: search_and_play(kw["query"]),
    "media_control": lambda **kw: media_control(kw["action"]),
    "system_info": lambda **kw: pc_system_info(),
    "list_processes": lambda **kw: list_processes(),
    "active_window": lambda **kw: active_window(),
    "read_clipboard": lambda **kw: read_clipboard(),
    "write_clipboard": lambda **kw: write_clipboard(kw["text"]),
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
    "send_email": lambda **kw: send_email(kw["to"], kw.get("subject", ""), kw.get("body", "")),
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
    "read_own_file": lambda **kw: read_own_file(kw["path"]),
    "list_own_files": lambda **kw: list_own_files(kw.get("directory", "")),
    "search_own_code": lambda **kw: search_own_code(kw["query"]),
    "get_own_commits": lambda **kw: get_own_commits(int(kw.get("limit") or 10)),
    "get_own_issues": lambda **kw: get_own_issues(kw.get("state", "open")),
    "create_own_branch": lambda **kw: create_own_branch(
        kw["branch_name"], kw.get("from_branch", "main"),
    ),
    "create_own_file": lambda **kw: create_own_file(
        kw["path"], kw["content"], kw["message"], kw.get("branch", "main"),
    ),
    "create_own_pr": lambda **kw: create_own_pr(
        kw["title"], kw.get("body", ""), kw["head"], kw.get("base", "main"),
    ),
    "create_own_issue": lambda **kw: create_own_issue(
        kw["title"], kw.get("body", ""), kw.get("labels") or [],
    ),
    "comment_own_issue": lambda **kw: comment_own_issue(int(kw["issue_number"]), kw["body"]),
    "check_for_updates": lambda **kw: check_and_prompt_update(),
    "apply_update": lambda **kw: _format_update_result(apply_update()),
    "restart_jarvis": lambda **kw: restart_jarvis(),
    "read_dev_log": lambda **kw: read_dev_log(),
    "get_dev_log_summary": lambda **kw: get_dev_log_summary(),
    "append_dev_log_entry": lambda **kw: append_dev_log_entry(
        kw["summary"], kw.get("author", ""),
    ),
    "make_call": lambda **kw: make_call(kw["to"], kw.get("purpose", "")),
    "end_call": lambda **kw: end_call(kw.get("call_sid", "")),
    "get_call_status": lambda **kw: get_call_status(kw.get("call_sid", "")),
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
    "read_own_file",
    "list_own_files",
    "search_own_code",
    "get_own_commits",
    "get_own_issues",
    "read_dev_log",
    "get_dev_log_summary",
    "get_battery_status",
    "get_system_info",
    "system_info",
    "list_processes",
    "active_window",
    "read_clipboard",
    "find_file",
    "get_recent_files",
    "open_downloads",
    "open_desktop",
    "check_for_updates",
    "get_call_status",
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
    # send_email — intentionally AUTO_ALLOW for voice-first UX.
    # Dashboard path still requires confirm modal (see DASHBOARD_CONFIRM_TOOLS).
    # Risk accepted: misheard commands could send email. Documented design decision.
    "send_email",
})

# Moderate-risk tools — dashboard confirm in voice mode when confirm_before_execute is on.
MODERATE_TOOLS = frozenset({
    "enable_login_item",
    "disable_login_item",
    "manage_startup",
    "music_play",
    "music_pause",
    "music_skip",
    "music_previous",
    "music_set_volume",
    "get_now_playing",
    "search_and_play",
    "media_control",
    "write_clipboard",
    "create_own_branch",
    "create_own_issue",
    "comment_own_issue",
    "append_dev_log_entry",
    "end_call",
})

# High-risk mutating tools — dashboard confirm required when confirm_before_execute is on.
CONFIRM_REQUIRED_TOOLS = frozenset({
    "download_file",
    "append_row",
    "update_cell",
    "send_slack_message",
    "create_github_comment",
    "create_pitch_deck",
    "create_own_file",
    "create_own_pr",
    "apply_update",
    "restart_jarvis",
    "make_call",
})

# Dashboard /api/tools/run two-step confirm. Includes voice auto-allow tools that
# are still too risky to run from the UI without explicit confirmation.
DASHBOARD_CONFIRM_TOOLS = CONFIRM_REQUIRED_TOOLS | MODERATE_TOOLS | frozenset({"send_email"})

# Phone callers cannot use the dashboard confirm gate — only read-only + escalate.
PHONE_ALLOWED_TOOLS = READ_ONLY_TOOLS | frozenset({"escalate"})

# Self-modifying / ops tools — only safe to expose when Jarvis runs on a dev's own
# machine against their own GitHub repo. Hidden entirely (not just confirm-gated)
# when Config.developer_mode is False, e.g. for non-dev installs.
DEV_ONLY_TOOLS = frozenset({
    "create_own_branch",
    "create_own_file",
    "create_own_pr",
    "create_own_issue",
    "comment_own_issue",
    "apply_update",
    "restart_jarvis",
})


# Demo allowlist — the small, reliable set of tools exposed when Config.demo_mode is
# True. Everything else is hidden so nothing can misfire during a live demo. Reversible:
# flip demo_mode off in config.json to restore the full toolset. Nothing is deleted.
DEMO_TOOLS = frozenset({
    "get_todays_schedule",  # calendar — today
    "get_calendar_events",  # calendar — arbitrary day/range
    "get_unread_emails",    # gmail — unread
    "search_emails",        # gmail — find an email (read-only; send_email left out for demo safety)
    "get_weather",          # weather
    "web_search",           # answer general questions
    "remember",             # take a note / remember a fact
    "search_and_play",      # play music
})


def get_tool_definitions(developer_mode: bool = True, demo_mode: bool = False) -> list[dict]:
    """Tool definitions to expose to the model.

    demo_mode wins: it exposes only the DEMO_TOOLS allowlist. Otherwise the full set,
    minus self-modifying DEV_ONLY_TOOLS on non-dev installs.
    """
    if demo_mode:
        return [t for t in TOOL_DEFINITIONS if t["name"] in DEMO_TOOLS]
    if developer_mode:
        return TOOL_DEFINITIONS
    return [t for t in TOOL_DEFINITIONS if t["name"] not in DEV_ONLY_TOOLS]


def _format_update_result(result: dict) -> str:
    if result["success"]:
        return f"Update applied successfully. Jarvis moved from {result['old_sha'][:7]} to {result['new_sha'][:7]}. Say 'restart Jarvis' to activate it."
    return f"Update failed: {result['error']}"


def _format_memory_hits(hits: list[dict]) -> str:
    if not hits:
        return "No matching memories found."
    lines = []
    for hit in hits:
        lines.append(f"[{hit['source']}] {hit['chunk']}")
    return "\n\n".join(lines)


def phone_tool_allowed(name: str) -> bool:
    """True when a tool may run during a Twilio phone turn."""
    return name in PHONE_ALLOWED_TOOLS


def dispatch_tool(
    name: str,
    inputs: dict,
    confirm: bool = False,
    confirm_timeout_sec: int = 30,
    cancel_check: callable | None = None,
    developer_mode: bool = True,
    phone_mode: bool = False,
) -> str:
    """Execute a tool by name with the given inputs dict.

    When confirm=True, high-risk tools wait for dashboard Allow/Deny (with timeout).
    Low-risk mutating tools and all read-only tools run immediately.

    Returns the tool result as a plain string, or an error message if the tool
    name is not registered, is dev-only on a non-dev install, or confirmation
    was denied.
    """
    if name not in TOOL_DISPATCH:
        return f"Unknown tool: {name}"

    if not developer_mode and name in DEV_ONLY_TOOLS:
        return f"Tool '{name}' is unavailable (developer mode is off)."

    if phone_mode and not phone_tool_allowed(name):
        return (
            f"Tool '{name}' cannot run during a phone call. "
            "Offer to transfer the caller to a human."
        )

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
