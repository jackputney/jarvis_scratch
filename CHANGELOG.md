# Changelog

All notable changes to this project are documented here.

## Sprint 3 — Dashboard, macOS packaging, and integrations

Branch: `jack/sprint-3`

### Added

- **Onboarding wizard** — first-run PyQt6 setup flow (Ollama, models, Whisper, location) before the main app starts.
- **Global hotkey** — wake Jarvis without the wake word via pynput (`Ctrl+Shift+Space` by default, configurable).
- **macOS `.app` launcher** — PyInstaller bundle (`jarvis.spec`, `build_mac.sh`) with dev vs frozen path resolution in `paths.py`.
- **Native dashboard window** — PyWebView subprocess wrapper so the orb UI and dashboard can run together without blocking the main thread.
- **Launch at login** — macOS LaunchAgent helper (`tools/login_item.py`) with a Settings toggle and `/api/login-item`.
- **Music control** — AppleScript + Music.app on macOS; Spotify URI search stub on Windows (`tools/music.py`, dashboard Overview card).
- **Email triage view** — unread Gmail list with Claude-drafted replies and confirm-gated send (`/api/email/unread`, `/api/email/draft-reply`).
- **Calendar day view** — visual timeline with prev/next day navigation, location, and clickable `zoommtg://` links (`/api/calendar/day`).

### Tests

- **336 tests passing** (excluding orb UI visual regression).
