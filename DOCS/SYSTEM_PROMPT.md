# Jarvis System Prompt

## Where it lives

The system prompt is built in `pipeline.py` by two components:

| Component | Location | Purpose |
|-----------|----------|---------|
| `_SYSTEM_PROMPT_TEMPLATE` | `pipeline.py` (module-level constant) | The full prompt text as a `.format()` template |
| `_build_system_blocks()` | `pipeline.py` | Fills in runtime variables, appends memory block, returns Anthropic message blocks |

The prompt is **never a flat string at rest** — it is assembled fresh on every call to `_build_system_blocks()`, which runs once per voice or dashboard turn.

---

## Block structure

The prompt is split into two Anthropic message blocks:

### Block 1 — Static (cached)
```python
{
    "type": "text",
    "cache_control": {"type": "ephemeral"},
    "text": <filled _SYSTEM_PROMPT_TEMPLATE>,
}
```
Contains the full system prompt with runtime variables substituted. Stable within
a session, so Anthropic's prompt cache hits on every subsequent turn — reducing
latency and cost on the fast model.

### Block 2 — Dynamic (per-query)
```python
{
    "type": "text",
    "text": "Known facts about {developer_name}:\n{variables_block}\n\nRelevant memories:\n{notes_block}",
}
```
Contains the user's persisted key/value facts from `build_variables_block()` and
semantic recall notes from `build_recall_context()` (or recent notes if semantic
recall is disabled). Changes every turn so it is not cached.

---

## Runtime variables

These are substituted into `_SYSTEM_PROMPT_TEMPLATE` at build time:

| Variable | Source | Default | Notes |
|----------|--------|---------|-------|
| `{developer_name}` | `config.developer_name` | `"Jack"` | Set `"developer_name": "Oliver"` in `config.json` for Oliver's machine |
| `{platform}` | `platform.system()` | `"macOS"` / `"Windows"` | Auto-detected, never configured |
| `{platform_detail}` | `platform.machine()` | `"Apple Silicon"` / `"Intel Mac"` / `"Windows PC"` | Auto-detected |
| `{timezone}` | `config.timezone` or `datetime.now().astimezone().strftime("%Z")` | System TZ | Set `"timezone": "America/Los_Angeles"` in `config.json` to override |

---

## Prompt sections and their purpose

| Section | What it controls |
|---------|-----------------|
| **Intro** | Jarvis identity and high-level capability framing |
| **How you speak** | TTS-optimised output rules: no markdown, no filler, plain sentences, email flow |
| **How you act** | Tool-use discipline: call tools immediately, never guess time, never refuse to open apps |
| **Who you are working for** | Injects developer_name, platform, timezone so the model always knows the user context |
| **Your capabilities by platform** | Explicit list of what is available on macOS vs Windows — prevents hallucinated capabilities |
| **GitHub** | Single-repo access boundary — never asks which repo, always uses jackputney/jarvis_scratch |
| **Memory** | Reminds the model to use remember()/write_note()/search_memory() proactively |
| **Self-improvement** | Connects the model to the Jarvis Thinks suggestion system in the dashboard |
| **How you think** | Anti-sandbagging: tells the model to use its full capacity, narrate plans on multi-step tasks |
| **When you hit a wall** | Refusal-to-deflection conversion: instead of "I can't", explain why and offer to build it |
| **Your development awareness** | Architecture self-knowledge: sprint model, tools/ pattern, self-modification tools |
| **Voice UX rules** | Barge-in, follow-up window, high-risk action narration, graceful tool failure |

---

## How to tune the prompt

### Change Jarvis's personality or verbosity
Edit the **How you speak** section in `_SYSTEM_PROMPT_TEMPLATE`. The key levers:
- "1 to 3 sentences" controls response length — increase for more verbose replies
- The filler-phrase ban list can be extended
- The email-send flow instructions are here too

### Add a new platform capability
Add it to **Your capabilities by platform** under the appropriate OS subsection.
If it needs a tool-use instruction (like the open_app rule for Windows), add a
sentence to the `macOS only` / `Windows only` / always-available block.

### Change how Jarvis handles a new topic area (e.g. Notion, Twilio)
Add a new `##` section to `_SYSTEM_PROMPT_TEMPLATE` after **Memory**. Keep it
concise — the model reads this on every turn, so brevity is important.

### Adjust the developer name or timezone
In `config.json`:
```json
{
  "developer_name": "Oliver",
  "timezone": "America/New_York"
}
```
No code change needed. The values are picked up automatically on next restart.

---

## How to add a new template variable

1. Add `{my_variable}` to `_SYSTEM_PROMPT_TEMPLATE` where needed.
2. In `_build_system_blocks()`, compute the value from `cfg` or the system.
3. Add `my_variable=value` to the `.format()` call at the end of the variable-building block.
4. If the value is user-configurable, add the field to `Config` in `config.py` and
   add the field name to `_PERSISTED_FIELDS`.
5. Update this doc.

---

## Debug

The first 200 characters of the built prompt are logged at `DEBUG` level on every
call to `_build_system_blocks()`. To see them:

```bash
# Set log level to DEBUG in your shell before starting Jarvis:
JARVIS_LOG_LEVEL=DEBUG python main.py
```

The log line looks like:
```
DEBUG jarvis.pipeline 🧠 System prompt preview: You are Jarvis — a local AI assistant running on macOS for Jack...
```

---

## What changed in Sprint 9

Previous system prompt:
- Single flat string `STATIC_SYSTEM_INSTRUCTIONS`
- No developer name, no platform detail in the static block
- OS-specific hints were tacked on in a separate dynamic string in `_build_system_blocks()`
- No self-improvement, memory, or "how you think" guidance

New system prompt:
- Full structured prompt covering 12 topic areas
- Runtime variables (`{developer_name}`, `{platform}`, `{platform_detail}`, `{timezone}`)
- Platform capability split baked in — macOS/Windows sections are in the static block
- Added sections: How you think, When you hit a wall, Your development awareness
- OS hints merged into the main prompt instead of scattered in Python strings
