"""memory — local persistent storage for Jarvis.

Two-tier storage:
  1. variables.db  — SQLite key-value store for structured facts.
  2. knowledge/    — Flat folder of Markdown files, one per topic.
"""
