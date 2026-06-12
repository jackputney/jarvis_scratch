# Orchestrator queue policy (Phase 1 decision)

## Chosen model: **bounded queue** (not hard reject)

| Behaviour | Phase 0 (today) | Phase 1 (target) |
|-----------|-----------------|------------------|
| Second command while busy | **Reject** — `busy: true`, dashboard **409** | **Enqueue** — runs after current job finishes |
| Overflow (queue full) | N/A | **Reject** — same busy message as today |
| Default max depth | 0 (no queue) | **3** commands |

## Why queue for a personal assistant

- Natural voice flow: you can ask a follow-up while Jarvis is still speaking or
  thinking; it runs in order instead of being ignored.
- Dashboard + voice can both submit without racing to be "first".
- Bounded cap prevents stale commands piling up ("play music" from 10 minutes ago).

## Why keep reject on overflow

- Safety valve when the user spams wake word or hammers Send.
- Same user-facing copy as Phase 0 (`BUSY_MESSAGE`).

## Status: **shipped** (Phase 1, threaded)

Implemented in `orchestrator/core.py` as a single worker thread (the app is
threaded + PyQt + Flask, so no asyncio). `submit()` returns a `SubmitResult`:

```python
def submit(self, command: Command) -> SubmitResult:
    with self._cv:
        self._purge_stale_locked(...)              # drop commands older than 60s
        busy = self._current_job_id is not None
        if busy and len(self._queue) >= self._max_queue:   # default 3
            return SubmitResult(accepted=False, reason="busy")
        self._queue.append(command)
        self._cv.notify()                          # wake the worker
    return SubmitResult(accepted=True, job_id=command.id)
```

- **Voice** submits `speak=True` and waits for the turn (mic stays paused so
  Jarvis never hears itself); the orchestrator runs the query, drives state, and
  speaks the reply.
- **Dashboard** `/api/message` submits `speak=False` and waits for the reply text.
- **Stop** (`/api/interrupt`, orb button) calls `cancel_current()`: interrupts the
  running turn and drops everything still queued.
- Stale commands (age > `max_command_age_sec`, default 60 s) are marked
  `CANCELLED` (`error="stale"`) and never run.
- Overflow rejects with the same `BUSY_MESSAGE` as Phase 0 (HTTP 409 on the
  dashboard).

Tunables live on the `Orchestrator` constructor: `max_queue_depth` (3),
`max_command_age_sec` (60).
