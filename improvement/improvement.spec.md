# improvement — Stage 1 instrumentation

## Purpose

Record every interaction turn in SQLite for future reflection, scoring, and
suggestions. Stage 1 is **write-only instrumentation** — no LLM reflection, no
auto-apply.

## Principles

- Hot path never blocks on disk: all writes go through a single background writer thread.
- `improvement/` must not import `pipeline.py` or `registry.py` (hooks call inward).
- Human review gates apply to future `lessons` / `suggestions` (Stage 3+).

## Schema

Tables in `memory/variables.db` (WAL): `sessions`, `turns`, `events`,
`corrections`, plus empty `lessons`, `suggestions`, `baselines` for later stages.

## TurnTrace lifecycle

1. Orchestrator opens `TurnTrace` per command (session created on first turn).
2. Pipeline stashes STT metrics before `submit()`; orchestrator applies them.
3. Pipeline records tool calls via `record_tool_call()` during voice LLM loop.
4. TTS router records `tts_ms` and `tts_fallback` events.
5. On `__exit__`, turn row + queued events flush to the writer queue.

## Signals (Stage 1)

- `detect_correction(prev, curr)` — overlap / negation heuristics, no LLM.
- `detect_repeat_request(history, curr)` — repeat within window.

Corrections persisted when previous turn text is available at turn end.
