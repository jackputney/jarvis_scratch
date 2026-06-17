"""Shared pytest fixtures and environment for Jarvis tests."""

from __future__ import annotations

import os

# Headless Qt for orb/UI tests — avoids SIGABRT when no display server is attached
# (CI, sandbox, SSH). Real GUI runs use the native platform via ./run.sh.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
