"""Google Drive search and read (read-only)."""

from __future__ import annotations

from tools.google_auth import get_google_service

MAX_RESULTS = 5
MAX_CONTENT_CHARS = 5000

_EXPORT_MIME = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}


def _service():
    return get_google_service("drive", "v3")


def search_drive(query: str, max_results: int = MAX_RESULTS) -> str:
    service = _service()
    safe_query = query.replace("'", "\\'")
    resp = service.files().list(
        q=f"name contains '{safe_query}' and trashed = false",
        pageSize=max_results,
        fields="files(id, name, mimeType, modifiedTime)",
    ).execute()
    files = resp.get("files", [])
    if not files:
        return f"No Drive files found matching {query!r}."
    return "\n".join(
        f"{f['name']} (id: {f['id']}, modified {f.get('modifiedTime', '')})" for f in files
    )


def read_drive_file(file_id: str) -> str:
    service = _service()
    meta = service.files().get(fileId=file_id, fields="name, mimeType").execute()
    mime = meta.get("mimeType", "")
    if mime in _EXPORT_MIME:
        data = service.files().export(fileId=file_id, mimeType=_EXPORT_MIME[mime]).execute()
    elif mime.startswith("text/") or mime == "application/json":
        data = service.files().get_media(fileId=file_id).execute()
    else:
        return f"Cannot read {meta.get('name', file_id)!r}: unsupported type ({mime})."
    text = data.decode("utf-8") if isinstance(data, bytes) else str(data)
    if len(text) > MAX_CONTENT_CHARS:
        text = text[:MAX_CONTENT_CHARS] + "\n…[truncated]"
    return f"{meta.get('name', file_id)}:\n{text}"
