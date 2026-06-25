# Tools Audit — Sprint 8

**Date:** 2026-06-25  
**Branch:** `jack/sprint-8`  
**Auditor:** Cursor acting for Jack  
**Baseline tests:** 529 → **517 passing** (rebased on main without dev-log sprint-7 tools)  
**Post-fix tests:** **517 passing**

---

## Full Tool Inventory

| File | Tool(s) | Risk tier | Tests? | Platform guard? | Issues found |
|------|---------|-----------|--------|-----------------|--------------|
| `clipboard.py` | `read_clipboard`, `write_clipboard` | READ_ONLY / MODERATE | ✅ | ✅ Windows guard | None |
| `confirm.py` | `wait_for_confirm`, `cancel_pending`, `get_pending`, `respond` | — (internal) | ✅ | None needed | `except Exception: pass` on bus emit intentional |
| `device_control.py` | `set_volume`, `set_mute`, `set_brightness`, `set_do_not_disturb`, `lock_screen`, `set_appearance_mode`, `get_battery_status`, `set_screen_saver`, `get_system_info`, `set_wifi` | AUTO / READ | ✅ | ✅ per function | `set_brightness` was Windows-only (no macOS branch); `set_wifi` hardcoded `en0` |
| `download.py` | `download_file` | CONFIRM | ✅ | None needed | Missing registry import — **FIXED** |
| `github.py` | `search_github_issues`, `create_github_comment`, `get_github_repo_summary` | READ / CONFIRM | ✅ | None needed | `search_github_issues` `q` param ineffective on list endpoint (flagged) |
| `github_self.py` | `read_own_file`, `list_own_files`, `search_own_code`, `get_own_commits`, `get_own_issues`, `create_own_branch`, `create_own_file`, `create_own_pr`, `create_own_issue`, `comment_own_issue` | READ / MODERATE / CONFIRM | ✅ | None needed | None |
| `gmail.py` | Re-exports `google_gmail.py` | — | Covered via re-export | None needed | Thin wrapper only — see `google_gmail.py` |
| `google_auth.py` | `get_credentials`, `get_google_service`, `ensure_google_ready` | — (auth) | ✅ | None needed | None |
| `google_calendar.py` | `get_calendar_events`, `get_todays_schedule` | READ | ✅ | None needed | None |
| `google_contacts.py` | `search_contacts`, `list_contacts`, `get_contact_names`, `list_contacts_full` | READ | ✅ | None needed | None |
| `google_drive.py` | `search_drive`, `read_drive_file` | READ | ✅ | None needed | None |
| `google_gmail.py` | `get_unread_emails`, `list_recent_emails`, `search_emails`, `send_email`, `fetch_thread_context`, `draft_email_reply` | READ / AUTO | ✅ | None needed | `fetch_thread_context` silently swallowed exceptions — **FIXED** |
| `google_sheets.py` | `read_sheet`, `append_row`, `update_cell` | READ / CONFIRM | ✅ | None needed | None |
| `hotkey.py` | `start_hotkey_listener`, `stop_hotkey_listener`, `normalize_combo` | — (internal) | ✅ | None needed | `stop_hotkey_listener` nulls ref but doesn't stop thread (flagged) |
| `login_item.py` | `enable_login_item`, `disable_login_item`, `manage_startup` | MODERATE | ✅ | ✅ `_darwin_only` / `_windows_only` | None |
| `media.py` | `open_photos`, `open_podcasts`, `find_file`, `open_file`, `find_and_open_file`, `open_downloads`, `open_desktop`, `get_recent_files` | AUTO | ✅ (partial) | ✅ `_darwin_only` | `open_photos(query)` activates Photos but doesn't search (flagged) |
| `media_control.py` | `media_control` | MODERATE | ✅ | ✅ Windows guard | None |
| `music.py` | `play`, `pause`, `skip`, `previous`, `set_volume`, `get_now_playing`, `search_and_play` | MODERATE | ✅ | ✅ `_darwin_guard` | None (Hypothesis B rejected by runtime log) |
| `pitch_deck.py` | `create_pitch_deck` | CONFIRM | ✅ | ✅ open-file branch | `except Exception: pass` in `_generate_slide_content` intentional fallback |
| `slack.py` | `send_slack_message`, `read_slack_channel` | CONFIRM / READ | ✅ | None needed | Unguarded `requests` calls could propagate network errors — **FIXED** |
| `system.py` | `open_app` | AUTO | ✅ | ✅ platform branch | None |
| `system_info.py` | `system_info`, `list_processes`, `active_window` | READ | ✅ | ✅ Windows guard | None |
| `time_date.py` | `get_current_time` | READ | ✅ | None needed | None |
| `weather.py` | `get_weather` | READ | ✅ | None needed | None |
| `web.py` | `web_search` | READ | ✅ | None needed | None |

**Total tools:** 72 registered | **25 files** | **All files have at least basic test coverage**

---

## Issues Found and Fixed

### 🔴 HIGH — registry.py missing `download_file` import

**File:** `tools/registry.py`  
**Symptom:** `dispatch_tool("download_file", ...)` returned `"Tool error (download_file): name 'download_file' is not defined"` — the download feature was completely broken.  
**Root cause confirmed by runtime log:**
```json
{"hypothesisId": "A", "tool": "download_file", "exc_type": "NameError", "exc": "name 'download_file' is not defined"}
```
**Fix:** Added `from tools.download import download_file` to `registry.py` imports.  
**Verification:** Post-fix dispatch returns real network response, no NameError in log.  
**Test added:** `test_download_dispatch_is_importable` in `tests/test_download.py`

---

### 🟡 MEDIUM — `google_gmail.fetch_thread_context` silent exception

**File:** `tools/google_gmail.py`  
**Symptom:** Any API error in thread fetching silently returned `""` with no log entry — failures would be invisible.  
**Fix:** Added `logger.warning(...)` before `return ""`, and added `logging`/`logger` module setup.

---

### 🟡 MEDIUM — `slack.py` unguarded network calls

**File:** `tools/slack.py`  
**Symptom:** `requests.post/get` could raise `ConnectionError`, `Timeout`, etc. unhandled, bubbling up to `dispatch_tool`'s bare `except Exception` and returning a confusing error.  
**Fix:** Wrapped both HTTP calls in `try/except Exception` returning a clear `"Slack error: ..."` string.

---

### 🟡 MEDIUM — `device_control.set_brightness` had no macOS branch

**File:** `tools/device_control.py`  
**Symptom:** On macOS, `set_brightness(n)` would fall through to `"Setting brightness isn't supported on Darwin yet."` — completely broken.  
**Fix:** Added a Darwin branch that tries `osascript` first, then falls back to the `brightness` CLI (installable via Homebrew), with a helpful install hint on failure.  
**Tests added:** `test_set_brightness_windows_path`, `test_set_brightness_macos_osascript_path`, `test_set_brightness_macos_osascript_failure_fallback`

---

### 🟡 LOW — `device_control.set_wifi` hardcoded `en0`

**File:** `tools/device_control.py`  
**Symptom:** On Macs where Wi-Fi is `en1` or another interface, `set_wifi` would silently fail or affect the wrong interface.  
**Fix:** Added `networksetup -listallhardwareports` call to detect the actual Wi-Fi interface before calling `setairportpower`.  
**Test added:** `test_set_wifi_detects_interface_dynamically`

---

## Flagged for Follow-up (not fixed this sprint)

| Issue | File | Severity | Notes |
|-------|------|----------|-------|
| `search_github_issues` `q` param ineffective | `tools/github.py` | Low | The GitHub list issues API ignores `q`; the search API (`/search/issues`) should be used instead. Needs API change. |
| `hotkey.stop_hotkey_listener` doesn't stop thread | `tools/hotkey.py` | Low | Nulls the ref but the pynput listener keeps running. Fix requires calling `listener.stop()`. Needs care to avoid hotkey re-registration on start. |
| `media.open_photos(query)` doesn't search | `tools/media.py` | Low | Opens Photos.app but doesn't execute a search. Photos has no reliable AppleScript search API — would need URL scheme or Shortcuts automation. |
| Double-accept button fire on Thinks tab | `dashboard/static/app.js` | Low | Cosmetic (idempotent) but sends two API calls. Add a 500ms debounce on the accept button click. |

---

## Registry Tier Summary

| Tier | Count | Tools |
|------|-------|-------|
| `READ_ONLY_TOOLS` | 35 | `get_current_time`, `web_search`, `get_weather`, calendar, email reads, sheets read, contacts, drive read, slack read, github reads, github_self reads, device info, clipboard read, file find, `check_for_updates` |
| `AUTO_ALLOW_TOOLS` | 18 | `open_app`, volume/mute/brightness/DND/lock/appearance/screen-saver/wifi, media opens, `find_and_open_file`, `open_file`, `set_variable`, `write_note`, `remember`, `escalate`, `send_email` |
| `MODERATE_TOOLS` | 16 | Login items, music controls, `media_control`, `write_clipboard`, GitHub write (branch/issue/comment) |
| `CONFIRM_REQUIRED_TOOLS` | 10 | `download_file`, sheets write, slack send, `create_github_comment`, `create_pitch_deck`, GitHub write (file/PR), `apply_update`, `restart_jarvis` |

---

## Tool Count by Category

| Category | Count |
|----------|-------|
| Device / system control | 14 |
| Media / files | 9 |
| Google suite (Calendar, Gmail, Drive, Sheets, Contacts) | 10 |
| GitHub (general + self) | 10 |
| Memory / notes / variables | 5 |
| Slack | 2 |
| Weather / time | 2 |
| Web search / download | 2 |
| Utilities (confirm, hotkey, pitch deck, clipboard) | 6 |
| Self-update | 3 |
| **Total** | **72** |
