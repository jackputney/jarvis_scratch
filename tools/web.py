"""
tools/web.py — Web search via Brave Search API with DuckDuckGo fallback.
"""

from __future__ import annotations

import html
import os
import re
import time

DDG_HTML_URL = "https://html.duckduckgo.com/html/"
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
REQUEST_TIMEOUT = 10
MAX_RESULTS = 5
MAX_RESULT_CHARS = 1200
MAX_ATTEMPTS = 2
RETRY_BACKOFF = 1.5

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}

_SNIPPET_RE = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(fragment: str) -> str:
    text = _TAG_RE.sub("", fragment)
    return html.unescape(text).strip()


def _brave_search(query: str, count: int = MAX_RESULTS) -> str | None:
    from config import Config

    cfg = Config.load()
    api_key = (cfg.brave_api_key or os.environ.get("BRAVE_API_KEY", "")).strip()
    if not api_key:
        return None
    try:
        import requests
    except ImportError as exc:
        return f"Search failed: {exc}"
    try:
        resp = requests.get(
            BRAVE_URL,
            params={"q": query, "count": count},
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": api_key,
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return f"Search failed: {exc}"
    results = []
    for item in data.get("web", {}).get("results", [])[:count]:
        title = item.get("title", "")
        url = item.get("url", "")
        desc = item.get("description", "")
        results.append(f"**{title}**\n{url}\n{desc}")
    if not results:
        return f"No web results found for: {query}"
    return "\n\n".join(results)[:MAX_RESULT_CHARS]


def _ddg_fallback(query: str) -> str:
    try:
        import requests
    except Exception as exc:  # noqa: BLE001
        return f"Search failed: {exc}"
    rate_limited = False
    for _attempt in range(MAX_ATTEMPTS):
        try:
            response = requests.post(
                DDG_HTML_URL,
                data={"q": query},
                headers=_HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            return f"Search failed: {exc}"
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
        return "Search temporarily unavailable: DuckDuckGo rate-limited (HTTP 202)."
    return f"No web results found for: {query}"


def web_search(query: str) -> str:
    brave = _brave_search(query)
    if brave is not None:
        return brave
    return _ddg_fallback(query)
