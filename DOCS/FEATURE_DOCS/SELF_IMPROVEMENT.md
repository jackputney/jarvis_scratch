# Self-Improvement Engine

<!-- Last updated: 2026-06-22 | Updated by: Claude acting for Jack -->

## What it does

Jarvis records every interaction, analyses its own performance, and surfaces concrete improvement suggestions in the "Jarvis Thinks" dashboard view. Suggestions can be accepted and sent to Cursor for implementation.

## Files involved

| File | Role |
|------|------|
| `improvement/trace.py` | TurnTrace context manager, background write queue |
| `improvement/signals.py` | `detect_correction()`, `detect_repeat_request()` |
| `improvement/reflect.py` | heuristic metrics + haiku judge + suggestions |
| `improvement/stats.py` | `compute_stats()`, `fetch_turns()`, `fetch_events()` |
| `memory/db.py` | 7 new tables (sessions, turns, events, corrections, lessons, suggestions, baselines) |
| `orchestrator/core.py` | TurnTrace wraps every command, `_mark_speaking` hook |
| `pipeline.py` | STT confidence stash, tool call recording (thin hooks) |
| `tts/router.py` | tts_ms recording, tts_fallback event |
| `dashboard/templates/` | Jarvis Thinks view |
| `dashboard/app.py` | GET/POST suggestions API |

## How it works

### Stage 1 — Instrumentation (complete)

Every voice turn is recorded non-blocking:

```
Turn starts → TurnTrace opens (orchestrator)
STT runs → confidence + timing stashed (pipeline)
Claude runs → tokens + llm_ms recorded
TTS runs → provider + tts_ms recorded
Turn ends → TurnTrace writes to SQLite via background thread
```

### Stage 2 — Score + Baseline (not started)

- Golden set: 30–50 labelled conversations in `tests/evals/golden.jsonl`
- Haiku judge: binary pass/fail per turn (not 1–10 scales)
- `baselines` table populated with p50/p95/p99 metrics

### Stage 3 — Reflect + Surface (complete)

Nightly (APScheduler) or on-demand via dashboard:

```
reflect.py pulls last 100 turns
→ compute_period_metrics() — correction_rate, tool_error_rate, etc.
→ haiku generates structured Suggestion
→ suggestions table
→ Jarvis Thinks dashboard view
```

### Stage 4 — Research Loop (not started)

- Weekly PyPI poll for library updates
- Claude web_search for changelog summaries
- Findings → new suggestions

## DB tables (all in variables.db, WAL mode)

```sql
sessions(session_id, started_at, platform, app_version, model)
turns(turn_id, session_id, ts, source, wake_latency_ms, stt_text,
      stt_confidence, stt_ms, llm_ms, tool_ms, tts_ms, total_ms,
      model, tokens_in, tokens_out, cache_read_tokens, interrupted, cancelled)
events(event_id, turn_id, ts, type, payload_json)
corrections(correction_id, turn_id, prev_turn_id, kind)
lessons(id, created_at, category, text, status, evidence_turn_ids, votes)
suggestions(id, created_at, title, body, category, severity,
            status, evidence_json, proposed_change)
baselines(id, created_at, metric, p50, p95, p99, value)
```

## API endpoints

```
GET  /api/improvement/stats
GET  /api/improvement/turns?limit=50&session_id=
GET  /api/improvement/events?turn_id=
GET  /api/improvement/suggestions?status=pending
POST /api/improvement/suggestions/<id>/accept
POST /api/improvement/suggestions/<id>/dismiss
POST /api/improvement/suggestions/generate
```

## Dashboard — Jarvis Thinks view

- Stats bar: correction rate, tool error rate, avg latency, tts fallback rate
- Suggestion cards with severity badges (critical/high/medium/low)
- Accept → marks accepted, shows "Send to Cursor" button (copies to clipboard)
- Dismiss → removes from pending
- Refresh → triggers immediate `reflect.py` run
- Auto-refreshes every 30 minutes

## Gotchas

- `improvement/` has ZERO imports from `pipeline.py` or `registry.py` — decoupled by design
- Write queue is a daemon thread — turns write asynchronously, <5 ms hot path cost
- `reflect.py` uses haiku ONLY — never sonnet (cost control)
- Suggestions are proposals — Jarvis never auto-applies code changes
- Stage 2–4 not yet built — Jarvis Thinks will have limited data until Stage 2 runs

## How to test

```bash
# After a voice turn:
curl -s http://127.0.0.1:7777/api/improvement/stats | python3 -m json.tool

# Trigger reflection manually:
curl -s -X POST http://127.0.0.1:7777/api/improvement/suggestions/generate

# Check suggestions:
curl -s http://127.0.0.1:7777/api/improvement/suggestions | python3 -m json.tool

# Run tests:
pytest tests/improvement/
```
