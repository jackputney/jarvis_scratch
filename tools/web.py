"""
tools/web.py — Web search tool for Jarvis via DuckDuckGo.

Uses the DuckDuckGo HTML endpoint (html.duckduckgo.com/html/), which performs a
real web search and returns ranked result snippets — unlike the Instant Answer
API, which only covers a narrow set of encyclopedic topics and returns nothing
for everyday queries (weather, prices, "capital of France", etc.).

No API key required. Returns a concise plain-text summary of the top results so
Claude can ground its answer in real information. Always returns an honest,
explicit failure string rather than silently returning empty.
"""

from __future__ import annotations

import html
import re
import time

DDG_HTML_URL = "https://html.duckduckgo.com/html/"
REQUEST_TIMEOUT = 8  # seconds
MAX_RESULTS = 3
MAX_RESULT_CHARS = 600
MAX_ATTEMPTS = 2          # one retry on a rate-limit response
RETRY_BACKOFF = 1.5       # seconds between attempts

# DuckDuckGo blocks requests without a browser-like User-Agent.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}

_SNIPPET_RE = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(fragment: str) -> str:
    """Remove tags and unescape entities from an HTML fragment."""
    text = _TAG_RE.sub("", fragment)
    return html.unescape(text).strip()


def web_search(query: str) -> str:
    """Search DuckDuckGo and return a short plain-text summary of the top results.

    Args:
        query: The search string.

    Returns:
        A plain-text summary of the top results, or an explicit failure message
        if the request failed, was rate-limited, or genuinely returned no results.
    """
    try:
        import requests  # lazy import so registry loads without requests installed
    except Exception as exc:  # noqa: BLE001
        return f"Search failed: {exc}"

    rate_limited = False
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = requests.post(
                DDG_HTML_URL,
                data={"q": query},
                headers=_HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001 — surface any network error honestly
            return f"Search failed: {exc}"

        # DuckDuckGo serves an anti-bot "anomaly" page as HTTP 202 when it
        # rate-limits the caller. That is not a "no results" condition — report
        # it honestly so Claude doesn't claim the topic doesn't exist.
        if response.status_code == 202:
            rate_limited = True
            time.sleep(RETRY_BACKOFF)
            continue

        if response.status_code != 200:
            return f"Search failed: DuckDuckGo returned HTTP {response.status_code}."

        snippets: list[str] = []
        for raw in _SNIPPET_RE.findall(response.text):
            clean = _strip_html(raw)
            if clean:
                snippets.append(clean)
            if len(snippets) >= MAX_RESULTS:
                break

        if snippets:
            return "\n".join(f"- {s}" for s in snippets)[:MAX_RESULT_CHARS]
        return f"No web results found for: {query}"

    if rate_limited:
        return (
            "Search temporarily unavailable: DuckDuckGo is rate-limiting requests "
            "(HTTP 202). Try again in a moment."
        )
    return f"No web results found for: {query}"
