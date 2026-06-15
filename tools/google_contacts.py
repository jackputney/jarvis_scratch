"""Google Contacts via People API."""

from __future__ import annotations

import time
from difflib import SequenceMatcher

from tools.google_auth import get_google_service

MAX_RESULTS = 5
PAGE_SIZE = 200
CACHE_TTL_SECONDS = 300
MATCH_THRESHOLD = 0.65
CONFIDENT_THRESHOLD = 0.95

_cache: dict = {"ts": 0.0, "people": []}


def _service():
    return get_google_service("people", "v1")


def _all_contacts() -> list[dict]:
    now = time.time()
    if _cache["people"] and now - _cache["ts"] < CACHE_TTL_SECONDS:
        return _cache["people"]
    service = _service()
    people: list[dict] = []
    page_token: str | None = None
    while True:
        resp = service.people().connections().list(
            resourceName="people/me",
            pageSize=PAGE_SIZE,
            personFields="names,emailAddresses,phoneNumbers",
            pageToken=page_token,
        ).execute()
        people.extend(resp.get("connections", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    page_token = None
    while True:
        resp = service.otherContacts().list(
            pageSize=PAGE_SIZE,
            readMask="names,emailAddresses",
            pageToken=page_token,
        ).execute()
        people.extend(resp.get("otherContacts", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    _cache["ts"] = now
    _cache["people"] = people
    return people


def _display_names(person: dict) -> list[str]:
    return [n.get("displayName", "") for n in person.get("names", []) if n.get("displayName")]


def _score(query: str, name: str) -> float:
    q, n = query.lower().strip(), name.lower().strip()
    if not q or not n:
        return 0.0
    if q == n:
        return 1.0
    if q in n or n in q:
        return 0.95
    best = SequenceMatcher(None, q, n).ratio()
    q_tokens, n_tokens = q.split(), n.split()
    if q_tokens and n_tokens:
        token_scores = [max(SequenceMatcher(None, qt, nt).ratio() for nt in n_tokens) for qt in q_tokens]
        best = max(best, sum(token_scores) / len(token_scores))
    return best


def _best_score(query: str, person: dict) -> float:
    names = _display_names(person)
    return max((_score(query, name) for name in names), default=0.0)


def _format_person(person: dict) -> str:
    names = person.get("names", [{}])
    display = names[0].get("displayName", "(unknown)") if names else "(unknown)"
    emails = ", ".join(e.get("value", "") for e in person.get("emailAddresses", []))
    phones = ", ".join(p.get("value", "") for p in person.get("phoneNumbers", []))
    line = display
    if emails:
        line += f" — {emails}"
    if phones:
        line += f" — {phones}"
    return line


def search_contacts(query: str, max_results: int = MAX_RESULTS) -> str:
    scored = [(p, _best_score(query, p)) for p in _all_contacts()]
    matches = sorted(
        (item for item in scored if item[1] >= MATCH_THRESHOLD),
        key=lambda item: item[1],
        reverse=True,
    )[:max_results]
    if not matches:
        return f"No contacts found matching {query!r}."
    lines = [_format_person(p) for p, _ in matches]
    if matches[0][1] < CONFIDENT_THRESHOLD:
        lines.insert(0, f"Closest matches for {query!r}:")
    return "\n".join(lines)


def list_contacts(count: int = 10) -> str:
    people = _all_contacts()[: max(1, min(int(count), 50))]
    if not people:
        return "No contacts found."
    return "\n".join(_format_person(p) for p in people)
