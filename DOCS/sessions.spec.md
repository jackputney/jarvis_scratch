# Sessions Architecture — Interface Contract

**Status:** Spec (Phase 1 design — not yet implemented)  
**Branch target:** `jack/sprint-9` (Jack owns orchestrator/; Oliver owns pipeline.py)  
**Depends on:** orchestrator/core.py, orchestrator/types.py, pipeline.py  
**Must not break:** All 72 tools, TTS router, memory/SQLite, self-improvement TurnTrace

---

## Why sessions

The current architecture is **single-turn**: one wake → one reply → IDLE. Follow-ups are a heuristic (a 10-second re-listen window), not a first-class concept.

Sessions make conversations explicit:
- A voice interaction from first wake to last follow-up is one **session**
- Background tasks (calendar reminders, Twilio calls) run in a separate **lane** with their own session
- `TurnTrace` rows gain a `session_id` foreign key so multi-turn costs and timings aggregate correctly
- The dashboard shows active sessions instead of just the most recent turn

---

## Core concepts

### Session

```
Session
  id: str (uuid4)
  lane: LaneType          # VOICE | BACKGROUND
  source: CommandSource   # VOICE | SCHEDULE | WEBHOOK | ...
  created_at: float
  last_active_at: float
  state: SessionState     # ACTIVE | IDLE | CLOSED
  turns: list[Turn]       # appended by the pipeline
  metadata: dict          # caller_id for Twilio, event_id for Calendar, etc.
```

A session is **open** as long as the user might continue it. The voice lane session stays open through the follow-up window even when the pipeline returns to wake-word detection; it closes when the idle timeout fires or a new wake-word starts a fresh conversation.

### Lane

```
LaneType: VOICE | BACKGROUND

Lane
  type: LaneType
  session: Session | None
  busy: bool
```

**Lane A (voice):** The existing pipeline. At most one active session at a time. New wake-words during an open session *continue* that session; they don't create a new one unless the session has been closed.

**Lane B (background):** Proactive triggers and background jobs. Can queue tasks; the voice lane is never blocked by background work. If a background session needs to speak, it waits for Lane A to be idle.

### Turn

A single request–response pair within a session. Replaces the current single-turn `Job`:

```
Turn
  id: str
  session_id: str
  command: Command
  reply: str
  tools_used: list[str]
  model: str
  latency_ms: int
  cost: float
  trace_id: str           # links to TurnTrace row in SQLite
```

---

## File layout

```
orchestrator/
  core.py          — Orchestrator class (existing; gains session routing)
  session.py       — Session dataclass, SessionStore, lifecycle helpers  [NEW]
  lanes.py         — LaneA/LaneB managers, routing logic                [NEW]
  events.py        — EventBus (existing; gains session_id on payloads)
  runtime.py       — global singletons (existing; exposes active_session())
  types.py         — Command, Job, JobState, Turn (existing + Turn added)
  QUEUE_POLICY.md  — unchanged
```

---

## orchestrator/session.py — interface contract

```python
class SessionState(str, Enum):
    ACTIVE = "active"
    IDLE   = "idle"     # pipeline back at wake-word, session still open
    CLOSED = "closed"

@dataclass
class Session:
    id: str
    lane: LaneType
    source: CommandSource
    created_at: float
    last_active_at: float
    state: SessionState
    turns: list[Turn]
    metadata: dict[str, Any]

    def add_turn(self, turn: Turn) -> None: ...
    def touch(self) -> None: ...           # update last_active_at
    def close(self) -> None: ...          # set state = CLOSED

class SessionStore:
    """In-memory registry of open sessions. Thread-safe."""

    def create(self, lane: LaneType, source: CommandSource, **metadata) -> Session: ...
    def get(self, session_id: str) -> Session | None: ...
    def get_active(self, lane: LaneType) -> Session | None: ...
    def close(self, session_id: str) -> None: ...
    def close_idle(self, older_than_sec: float) -> int: ...  # returns count closed
    def all_active(self) -> list[Session]: ...
```

---

## orchestrator/lanes.py — interface contract

```python
class LaneType(str, Enum):
    VOICE      = "voice"
    BACKGROUND = "background"

class VoiceLane:
    """Wraps the existing Orchestrator for Lane A.

    Key changes from current Orchestrator:
    - submit() accepts an optional session_id; if None, creates a new session
      OR continues the most-recently-active session if within idle_timeout
    - The returned Job carries session_id and turn_id
    - On barge-in: marks the current turn cancelled, keeps the session open
    """

    def submit(
        self,
        command: Command,
        session_id: str | None = None,
    ) -> SubmitResult: ...

    def active_session(self) -> Session | None: ...
    def is_busy(self) -> bool: ...


class BackgroundLane:
    """Runs proactive and scheduled tasks without blocking the voice lane.

    Phase 2: triggered by EventBus subscribers (calendar, GitHub webhook, cron).
    Phase 1: can be used manually for long-running tool tasks.
    """

    def submit(
        self,
        command: Command,
        speak_when_idle: bool = True,
    ) -> SubmitResult: ...

    def cancel_all(self) -> int: ...  # returns count cancelled
    def is_busy(self) -> bool: ...
```

---

## pipeline.py changes (Oliver owns)

> **Coordinated file — message Oliver before editing.**

### Summary of required changes

1. **Session creation:** On wake-word detect, call `voice_lane.active_session()`. If a session is open and within `conversation_idle_timeout_sec`, continue it; otherwise create a new one via `session_store.create(...)`.

2. **session_id threading:** Pass `session_id` to `process_query()`, which writes it to `TurnTrace`. The session context (last N turns) replaces the current `conversation_history` list — the session IS the history.

3. **Follow-up window → session idle:** After a reply, instead of a fixed re-listen window, the session transitions to `IDLE`. The pipeline listens for the next wake-word (or timeout). On timeout, the session closes; on wake-word, it continues.

4. **Barge-in:** Closes the current *turn* but keeps the session open. The next turn starts immediately without a new wake-word.

### API the pipeline must not change

These function signatures and event names must stay stable so orchestrator can route to them without changes to `core.py`:

```python
# Must remain importable from pipeline
process_query(text: str, session_id: str | None = None) -> dict[str, Any]
request_interrupt() -> None
request_wake() -> None
graceful_shutdown() -> None
```

---

## EventBus event payloads (updated)

All existing events gain `session_id: str | None`. New events:

| Event | When | Key payload fields |
|-------|------|--------------------|
| `session.created` | New session opened | `session_id`, `lane`, `source` |
| `session.continued` | Wake-word continues open session | `session_id`, `turn_count` |
| `session.idle` | Pipeline returned to wake-word, session open | `session_id`, `idle_since` |
| `session.closed` | Session closed (timeout or explicit) | `session_id`, `turn_count`, `duration_sec` |
| `lane.background.queued` | Background task enqueued | `session_id`, `command_preview` |
| `lane.background.spoke` | Background session spoke notification | `session_id`, `text_preview` |

Existing events unchanged (add `session_id=None` default):

| Event | Existing fields |
|-------|----------------|
| `job.transcript` | `heard`, `reply`, `session_id` |
| `tool.run` | `name`, `ok`, `source`, `session_id` |
| `pipeline.state` | `state`, `session_id` |

---

## Dashboard changes (minimal)

- Add a `Sessions` panel to the Activity view showing active sessions: lane, source, turn count, age, state (ACTIVE / IDLE).
- `job.transcript` SSE events already flow to the activity feed; no structural change needed.
- Background lane notifications appear as a distinct card type (`lane-b-notification`).

---

## Open questions for Oliver

1. **Follow-up timeout → close or keep-idle?** Recommendation: keep session IDLE for `conversation_idle_timeout_sec` after the follow-up window expires. The user can still say the wake word within that window and continue. After the timeout, close. This avoids the abrupt "you have to start over" feel.

2. **Barge-in + background lane:** Barge-in should cancel only the current *voice turn*. It must not cancel background lane jobs unless the user explicitly says "cancel background task." Recommendation: barge-in sends `request_interrupt()` (voice only); background lane has its own `cancel_all()`.

3. **Twilio audio lane:** Telephony should create a VOICE lane session (it's a real-time conversation). The difference is the audio I/O: mic/speaker swap for Twilio's RTP stream. A `TelephonyLane` subclass of `VoiceLane` handles the audio swap; the session/turn model is identical.

---

## Migration path

| Phase | Ships independently | Unlocks |
|-------|--------------------|---------||
| **Phase 1** | `orchestrator/session.py` + `orchestrator/lanes.py` + pipeline `session_id` threading | Multi-turn cost tracking, background lane, Twilio |
| **Phase 2** | Proactive trigger subscribers (Calendar, GitHub, cron, HA) | Layer 4 ambient awareness |
| **Phase 3** | Multi-step agent tasks with checkpoints (pause/resume sessions) | Layer 5 autonomous tasks |

Each phase ships as its own PR. Phase 1 must not break any existing tool, TTS, or memory behaviour.

---

## What does NOT change

| Component | Status |
|-----------|--------|
| All 72 tools | Unchanged — no session awareness needed |
| TTS router | Unchanged — session context not relevant to voice synthesis |
| memory/SQLite | `TurnTrace` gains `session_id` column (nullable, backward-compatible migration) |
| Self-improvement | `TurnTrace.session_id` enables per-session reflection in future; no change to current reflect.py |
| Config | `conversation_idle_timeout_sec` reused as session idle timeout (no new config key) |
