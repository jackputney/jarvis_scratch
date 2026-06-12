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

## `submit()` sketch

```python
async def submit(self, command: Command) -> SubmitResult:
    async with self._lock:
        if self._current_task and len(self._queue) >= self._max_queue:
            return SubmitResult(accepted=False, reason="busy")
        self._queue.append(command)
        self._bus.emit("job.state", job_id=command.id, state="queued")
    self._pump.schedule()  # starts worker if idle
    return SubmitResult(accepted=True, job_id=command.id)
```

## Phase 0 bridge

Until Phase 1 ships, `process_query()` keeps the hard reject lock. Dashboard and
voice both get immediate feedback if a query is already in flight.
