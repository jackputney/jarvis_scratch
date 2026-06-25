# Jarvis Dev Log — Native Google Docs Append/Read

**Module:** `tools/dev_log.py`
**Branch introduced:** `jack/sprint-7`

---

## What it does

Stops the "new doc every session" problem. Jarvis can now read from and append to
a single shared Google Doc that acts as a running dev log for both Jack and Oliver.

Every session Jarvis can append an entry automatically (after reflection) or on voice
command. Both developers can ask "what did Oliver build today?" and get a live answer.

---

## Voice commands

| Phrase | Tool called | Tier |
|--------|-------------|------|
| "What did Oliver build today?" | `get_dev_log_summary` | READ_ONLY |
| "What happened recently?" | `get_dev_log_summary` | READ_ONLY |
| "Read the dev log" | `read_dev_log` | READ_ONLY |
| "Update the dev log with [summary]" | `append_dev_log_entry` | MODERATE |
| "Log this session" | `append_dev_log_entry` | MODERATE |

---

## Entry format

Every entry written to the doc looks like:

```
### 2026-06-25 14:30 | Jack's Claude
- Ran reflection: 3 suggestions generated
- Top issue: Reduce STT latency
- Branch: jack/sprint-7
---
```

- Header line: `### YYYY-MM-DD HH:MM | {author}`
- Each summary line is prefixed with `- ` (already-bulleted lines are kept as-is)
- Entries are inserted at the top of the `## LOG` section (newest first)

---

## Setting `dev_log_author` per machine

Each developer sets their own author name so entries are clearly attributed.

**Jack's machine (`config.json`):**
```json
{
  "dev_log_author": "Jack's Claude"
}
```

**Oliver's machine (`config.json`):**
```json
{
  "dev_log_author": "Oliver's Claude"
}
```

The Hub Settings UI (under General) also exposes `dev_log_author`.

---

## How Google Docs API auth works

The dev log tools use the same Google OAuth flow as Calendar, Gmail, and Sheets —
no extra credentials needed.

The `https://www.googleapis.com/auth/documents` scope was added to `tools/google_auth.py`
in this sprint. If your `memory/google_token.json` was created before this change,
delete it and restart Jarvis once. The browser-based sign-in will run again and
add the new scope to the stored token.

Steps to re-auth:
```bash
rm memory/google_token.json
./run.sh
# Browser opens once for sign-in, then Jarvis starts normally
```

---

## The doc ID

The current shared dev log is:

```
18OUXDja6GbV99dB_sv2iGlsLJTCqg3AQ95kvQbazQyc
```

This is the default value in `Config.dev_log_doc_id`. To use a different doc:

1. Create a new Google Doc.
2. Make sure your Google account has edit access.
3. Add a heading `## LOG` followed by `---` on the next line.
4. Set `dev_log_doc_id` in `config.json` to the new doc's ID.

The doc ID is the long string in the Google Docs URL:
```
https://docs.google.com/document/d/<DOC_ID>/edit
```

---

## Auto-append after reflection

When `GOOGLE_CLIENT_ID` is set and reflection runs successfully, Jarvis automatically
appends a brief summary entry:

```
- Ran reflection: N suggestions generated
- Top issue: {title}
- Branch: {git branch}
```

This is fire-and-forget — if the Docs API call fails (e.g. offline), it is silently
skipped and logged at DEBUG level only.

---

## Graceful degradation

All three tools fail gracefully:

| Condition | Behaviour |
|-----------|-----------|
| `dev_log_doc_id` not set | Returns a clear "not configured" message |
| `GOOGLE_CLIENT_ID` not set | Returns a helpful error asking the user to configure OAuth |
| Doc API error (network, permissions) | Returns a human-readable error string |
| `## LOG` section missing from doc | Returns a message explaining what heading is needed |
