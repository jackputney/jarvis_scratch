"""memory — local persistent storage for Jarvis.

Three-tier storage under a user-assigned folder (``memory_root_path`` in config):
  1. variables.db  — SQLite key-value store for structured facts.
  2. notes/        — Markdown files, one per topic.
  3. profile.md + diary/ — rolling user profile and daily conversation diary,
     indexed for semantic recall via FTS5 (see semantic.py).
"""
