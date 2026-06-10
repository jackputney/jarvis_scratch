"""
tools/registry.py — Central registry of all Jarvis tools.

Holds two things:
  1. TOOL_DEFINITIONS  — the Anthropic-format tool specs passed to Claude via tools=.
  2. TOOL_DISPATCH     — a plain dict mapping tool name → Python callable.

Adding a new tool means adding one entry in each dict. No decorator magic, no
class hierarchy — just explicit, readable mappings.
"""

from __future__ import annotations

from memory.variables import get_variable, set_variable
from memory.knowledge import read_note, write_note
from tools.system import open_app
from tools.web import web_search

# ---------------------------------------------------------------------------
# Anthropic tool definitions — passed verbatim as the tools= parameter.
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "open_app",
        "description": "Open a macOS application by name.",
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
        "description": "Search the web via DuckDuckGo and return a short text summary.",
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
}


def dispatch_tool(name: str, inputs: dict, confirm: bool = False) -> str:
    """Execute a tool by name with the given inputs dict.

    If confirm=True, prints the pending call and waits for a keypress before
    running — this is the lightweight permission gate.

    Returns the tool result as a plain string, or an error message if the tool
    name is not registered.
    """
    if name not in TOOL_DISPATCH:
        return f"Unknown tool: {name}"

    if confirm:
        # NOTE: confirm mode requires an interactive terminal. When launched
        # without a TTY (e.g. via launchd or a packaged .app), input() raises
        # EOFError immediately — we treat that as a denial and refuse to run
        # the tool rather than crashing or silently executing it.
        print(f"\n⚙️  Tool call: {name}({inputs})")
        try:
            input("   Press Enter to allow, Ctrl+C to cancel… ")
        except EOFError:
            return f"Tool '{name}' not executed: confirmation required but no interactive terminal is available."

    try:
        result = TOOL_DISPATCH[name](**inputs)
        return str(result) if result is not None else "Done."
    except Exception as exc:
        return f"Tool error ({name}): {exc}"
