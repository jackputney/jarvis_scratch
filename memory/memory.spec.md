# Semantic memory

Jarvis stores everything it learns about the user on disk in a **local memory folder**. Nothing is sent to a cloud memory service.

## Memory folder

Set `memory_root_path` in `config.json` (or Settings → Memory folder) to any path on your machine, e.g. `~/JarvisMemory`. When unset, the project `memory/` directory is used.

Layout under the root:

| Path | Purpose |
|------|---------|
| `notes/` (or `knowledge/` in legacy layout) | Topic Markdown notes |
| `profile.md` | Timestamped durable facts (`remember` tool) |
| `diary/YYYY-MM-DD.md` | Daily conversation log when auto-learn is on |
| `semantic_index.db` | FTS5 index for recall |
| `variables.db` | Structured key-value facts |

## Recall

Before each Claude call, Jarvis injects **relevant** memory snippets (not just the most recent notes) when `memory_semantic_recall` is true. Search uses SQLite FTS5 over chunked notes, profile, and diary.

When notes are injected by recency (`get_recent_notes`), each note is capped at **2,000 characters** and the combined block at **8,000 characters**, with a warning logged if truncation occurs.

## Learning

- **Explicit:** Jarvis uses `remember`, `set_variable`, and `write_note` tools when the user shares durable facts.
- **Automatic:** When `memory_auto_learn` is true, each completed turn is appended to today's diary and re-indexed.

## Privacy

All paths are gitignored. The memory folder is never uploaded. Users can inspect, edit, or delete files directly.

## API

- `GET /api/memory/info` — folder path and note count
- `GET /api/memory/search?q=` — semantic search hits
- `POST /api/memory/reindex` — rebuild FTS index

## Tools

| Tool | Behaviour |
|------|-----------|
| `remember` | Append fact to `profile.md` |
| `search_memory` | Query the local index |
| `write_note` / `read_note` | Topic notes |
| `set_variable` / `get_variable` | Structured facts |
