# Session Architecture Spec — DRAFT

> **Status:** Proposal from Oliver's side. Jack to review, mark up, and confirm before either side writes code.
>
> **Goal:** Replace the single-turn command model with sessions that support persistent context, background tasks, and multiple input sources — without breaking the existing voice UX.

---

## 1. What changes

### Today (v0.6.0)
```
wake → Command → Orchestrator queue → process_query → TTS → done
```
- Each command is independent. No shared context between turns (except conversation history in pipeline).
- One lane: voice. Everything blocks TTS.
- 60s stale drop, 180s voice timeout. Long tasks die.

### Proposed
```
Source → Session → Lane (voice | background) → process_query → Output
```
- A **Session** owns a conversation thread, tool state, and lifecycle.
- Two **Lanes** execute work: voice (real-time, TTS) and background (no timeout, reports when done).
- Multiple **Sources** can create sessions: wake word, Twilio call, dashboard, cron trigger.

---

## 2. Core types

### Session

```python
@dataclass
class Session:
    id: str                          # uuid4
    source: SessionSource            # VOICE, PHONE, DASHBOARD, TRIGGER
    created_at: float                # time.time()
    last_active: float               # updated on every interaction
    timeout_sec: float = 600.0       # 10 min default, configurable per source
    context: dict[str, Any]          # arbitrary state bag (Twilio stream_sid, call_sid, etc.)
    conversation: list[dict]         # message history for this session
    active_job_id: str | None = None
    background_jobs: list[str] = field(default_factory=list)
    state: SessionState = SessionState.ACTIVE

class SessionState(str, Enum):
    ACTIVE = "active"
    IDLE = "idle"          # waiting for user, not timed out yet
    SUSPENDED = "suspended" # backgrounded, can resume
    CLOSED = "closed"       # done, cleanup complete
```

**Lifecycle:**
1. Source creates session → `ACTIVE`
2. No interaction for N seconds → `IDLE`
3. Timeout expires → `CLOSED` (cleanup callback fires)
4. Explicit close (hangup, "that'll be all") → `CLOSED`
5. Background job running, user walks away → `SUSPENDED` (session stays alive until job finishes)

### SessionSource

```python
class SessionSource(str, Enum):
    VOICE = "voice"        # local wake word / hotkey
    PHONE = "phone"        # Twilio WebSocket
    DASHBOARD = "dashboard" # browser /api/run
    TRIGGER = "trigger"     # proactive event (cron, webhook, file watcher)
```

### Lane

```python
class Lane(str, Enum):
    VOICE = "voice"          # real-time TTS output, FIFO, barge-in enabled
    BACKGROUND = "background" # no TTS until done, no timeout, posts result to voice lane
```

---

## 3. Session manager

New file: `orchestrator/session.py` (Jack owns)

```python
class SessionManager:
    def create(source: SessionSource, context: dict = {}, timeout_sec: float = 600) -> Session
    def get(session_id: str) -> Session | None
    def get_active(source: SessionSource) -> Session | None  # latest active for this source
    def close(session_id: str) -> None
    def tick() -> None  # called periodically — expires idle sessions, emits events
```

**Rules:**
- Only **one active voice session** at a time (same as today's single-turn constraint).
- Phone sessions are independent — multiple concurrent calls are allowed.
- Dashboard sessions are ephemeral — created per request, closed after response.
- Trigger sessions are background-only — they queue a notification for voice when done.

---

## 4. Lane manager

New file: `orchestrator/lanes.py` (Jack owns)

```python
class LaneManager:
    def submit(session: Session, command: Command, lane: Lane = Lane.VOICE) -> SubmitResult
    def cancel(session_id: str) -> None  # cancel all jobs in session
    def get_active_jobs(session_id: str) -> list[Job]
```

**Voice lane** — same as today's orchestrator queue:
- FIFO, depth 3, 60s stale drop
- Barge-in cancels current job
- TTS streams as sentences arrive

**Background lane** — new:
- No queue depth limit (reasonable cap: 5 per session)
- No timeout (but session timeout still applies)
- Jobs run on a thread pool
- On completion, posts result to voice lane: "Your flight search found 3 options. Want to hear them?"
- If voice is busy, queues the notification

---

## 5. Pipeline changes

File: `pipeline.py` (Oliver owns)

### Current flow (preserved for voice)
```
wake → transcribe → submit(Command) → wait(job) → TTS → listen for followup
```

### New: session-aware flow
```
wake → get_or_create_session(VOICE) → transcribe → submit(session, Command) → wait → TTS → followup
```

Changes:
1. `run_pipeline()` creates a voice session on first wake, reuses it for follow-ups
2. Session closes on idle timeout or "that'll be all"
3. `process_query()` receives `session.conversation` instead of global conversation history
4. Tool dispatch can submit background jobs: `submit(session, Command(tool_task), Lane.BACKGROUND)`

### New: phone session flow
```
Twilio WebSocket connects → create_session(PHONE, context={stream_sid, call_sid})
  → continuous loop:
      receive mulaw → convert → transcribe → submit(session, Command) → wait
      → TTS via send_audio_to_caller() instead of local speakers
      → listen for next utterance (no wake word needed — session is already open)
  → WebSocket closes → close_session()
```

This maps cleanly to `twilio_server.py` which already has the WebSocket handler.

---

## 6. Confirm flow by source

| Source | Current | Proposed |
|--------|---------|----------|
| Voice | Dashboard modal (CONFIRM_REQUIRED tools) | Same — unchanged |
| Phone | N/A | Verbal: "Should I go ahead?" → listen for yes/no |
| Dashboard | HTTP confirm endpoint | Same — unchanged |
| Trigger | N/A | Queue notification, wait for voice confirm |

The `dispatch_tool()` function in `registry.py` needs a `confirm_mode` parameter:
- `"dashboard"` (default) — existing flow
- `"verbal"` — speak the question, wait for spoken yes/no via the session's input source

---

## 7. Event bus extensions

Existing events (unchanged):
- `job.state`, `job.transcript`, `pipeline.state`

New events:
- `session.created` — `{session_id, source}`
- `session.closed` — `{session_id, source, reason}`
- `session.timeout` — `{session_id, source}`
- `lane.background.complete` — `{session_id, job_id, result}`

---

## 8. Migration / backwards compat

- **Voice UX is unchanged.** A voice session is created implicitly on wake, closed on idle. The user doesn't know sessions exist.
- **Existing orchestrator queue stays.** The voice lane IS the current queue. LaneManager wraps it, doesn't replace it.
- **Existing tests keep passing.** SessionManager and LaneManager are additive — the old `orchestrator.submit(Command)` path still works (creates an ephemeral session internally).
- **Dashboard /api/run still works.** Creates a dashboard session, submits command, returns result.

---

## 9. File ownership

| File | Owner | Status |
|------|-------|--------|
| `orchestrator/session.py` | Jack | New |
| `orchestrator/lanes.py` | Jack | New |
| `orchestrator/core.py` | Jack | Modified — LaneManager wraps existing queue |
| `orchestrator/types.py` | Jack | Modified — add Session, SessionState, SessionSource, Lane |
| `orchestrator/events.py` | Jack | Modified — add new event types |
| `pipeline.py` | Oliver | Modified — session-aware voice loop |
| `twilio_server.py` | Oliver | Modified — wire to session manager |
| `tools/registry.py` | Oliver | Modified — verbal confirm path |

---

## 10. Open questions for Jack

1. **Session persistence:** Should sessions survive a Jarvis restart? (Probably not for v1 — in-memory only.)
2. **Background job thread pool:** Size? Shared with existing ThreadPoolExecutor in pipeline, or separate?
3. **Session-scoped conversation:** Does `conversation.build_messages()` pull from the session, or does session just hold a reference to the global conversation? (Session-scoped is cleaner for phone calls — a caller shouldn't see your local voice history.)
4. **Orchestrator.submit() wrapper:** Should the old `submit(Command)` auto-create an ephemeral session, or should we force all callers to pass a session? (Auto-create is safer for backwards compat.)
5. **Phone session concurrency:** Can Jarvis handle 2 phone calls at once? (Probably not in v1 — one phone session at a time, reject additional calls.)
