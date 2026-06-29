"""
dashboard/app.py — localhost Flask control panel for Jarvis.

Everything binds to 127.0.0.1 only. The app is intentionally tiny: one template,
one CSS file, vanilla JS. No build step, no React. State pushes over a Server-Sent
Events stream (/api/events) fed by the orchestrator bus; a slow poll is the
fallback. Text messages and Stop go through the shared orchestrator queue so the
dashboard and the voice loop never race.

Endpoints:
  GET  /                  → the dashboard page
  GET  /api/metrics        → session uptime + daily query/tool counts
  GET  /api/state         → pipeline state, mute, uptime, models, spend, log
  GET  /api/events        → Server-Sent Events stream of job/pipeline events
  GET  /api/tools         → tool definitions + risk tier (read/write/high)
  POST /api/tools/run     → {name, inputs} or {confirm_id, confirmed} for high-risk tools
  POST /hooks/<plugin_id> → webhook trigger for plugin automations
  POST /api/config        → update editable settings/budgets (writes config.json)
  GET  /api/variables     → all memory variables
  POST /api/variables     → add/edit a variable {key, value}
  DELETE /api/variables/<key>
  GET  /api/notes         → list note titles
  GET  /api/notes/<title> → one note's content
  POST /api/notes         → create/overwrite {title, content}
  DELETE /api/notes/<title>
  POST /api/message       → {text} → enqueue on the orchestrator, return reply (text)
  POST /api/interrupt     → cancel the running turn and clear the queue
  POST /api/confirm/respond → {id, allow} → resolve pending tool confirm
  GET  /api/hub/integrations → integration catalogue with live status
  GET  /api/hub/status       → health snapshot (services, orchestrator, plugins, spend)
  POST /api/hub/keys         → save integration credentials
  POST /api/hub/google/auth  → start Google OAuth (non-blocking)
  GET  /api/plugins          → list plugin manifests
  GET  /api/email/unread     → unread Gmail summaries for the triage view
  POST /api/email/draft-reply → Claude draft for replying to one message
  GET  /api/calendar/day     → calendar events for one day (YYYY-MM-DD)
  GET  /api/tts/voices       → ElevenLabs preset voices for the Settings picker
  POST /api/tts/preview      → speak a short sample {voice_id, text}
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from pathlib import Path

from flask import Flask, Response, jsonify, make_response, request

import costs
import events
from config import Config
from dashboard.hub_routes import hub_bp, list_plugin_manifests
from memory import knowledge, variables

from paths import dashboard_static_dir, dashboard_templates_dir

logger = logging.getLogger("jarvis.dashboard")

HOST = "127.0.0.1"
PORT = 7777
_START_TIME = time.time()
_STATIC_DIR = dashboard_static_dir()


def _static_version() -> str:
    """Cache-bust static assets when JS/CSS change."""
    try:
        mtimes = [_STATIC_DIR.joinpath(name).stat().st_mtime for name in ("app.js", "style.css", "hub.js")]
        return str(int(max(mtimes)))
    except OSError:
        return "1"


def _register_twilio_routes(app: Flask) -> None:
    """Mount TwiML webhook when Twilio credentials are configured."""
    try:
        from twilio_server import twilio_configured, _get_twiml_route

        if twilio_configured():
            app.register_blueprint(_get_twiml_route())
    except Exception:  # noqa: BLE001
        logger.warning("Twilio routes unavailable", exc_info=True)

# -- Server-Sent Events fan-out ---------------------------------------------
# The orchestrator emits job/state events on the shared bus; we mirror them to
# every connected browser so the UI updates instantly instead of polling hard.
_sse_clients: set[queue.Queue] = set()
_sse_lock = threading.Lock()
_sse_subscribed = False
_SSE_KEEPALIVE_SEC = 15.0
_SSE_QUEUE_MAX = 100


def _broadcast(event: str, payload: dict) -> None:
    if event == "pipeline.state":
        name = payload.get("state") or payload.get("pipeline_state") or "IDLE"
        payload = {
            **payload,
            "type": payload.get("type", "state"),
            "state": name,
            "pipeline_state": name,
        }
    msg = json.dumps({"event": event, **payload})
    with _sse_lock:
        clients = list(_sse_clients)
    for client in clients:
        try:
            client.put_nowait(msg)
        except queue.Full:
            pass  # slow client — drop this update, next poll reconciles


def _ensure_bus_subscription() -> None:
    global _sse_subscribed
    with _sse_lock:
        if _sse_subscribed:
            return
        _sse_subscribed = True
    try:
        from orchestrator.runtime import get_bus

        get_bus().subscribe(lambda event, payload: _broadcast(event, payload))
    except Exception:  # noqa: BLE001
        logger.debug("SSE bus subscription unavailable", exc_info=True)


def _pending_confirm() -> dict | None:
    try:
        from tools import confirm as tool_confirm
        return tool_confirm.get_pending()
    except Exception:  # noqa: BLE001
        return None


def _initial_sse_payloads() -> list[str]:
    """Catch-up events for new SSE subscribers (state + pending confirm)."""
    state = events.get_state()
    pipe = state.get("pipeline_state", "IDLE")
    payloads = [
        json.dumps({
            "event": "pipeline.state",
            "state": pipe,
            "type": "state",
            "pipeline_state": pipe,
            "muted": state.get("muted", False),
        }),
    ]
    pending = _pending_confirm()
    if pending:
        payloads.append(json.dumps({"event": "confirm.pending", "type": "confirm", **pending}))
    return payloads


def create_app() -> Flask:
    app = Flask(
        __name__,
        static_folder=str(dashboard_static_dir()),
        template_folder=str(dashboard_templates_dir()),
    )
    app.config["JSON_SORT_KEYS"] = False
    _ensure_bus_subscription()
    app.register_blueprint(hub_bp)
    _register_twilio_routes(app)

    # -- Page ---------------------------------------------------------------
    @app.route("/")
    def index():  # noqa: ANN202
        from flask import render_template

        resp = make_response(render_template("index.html", static_v=_static_version()))
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return resp

    # -- State (polled every 2s) -------------------------------------------
    @app.route("/api/state")
    def api_state():  # noqa: ANN202
        cfg = Config.load()
        state = events.get_state()
        return jsonify({
            "pipeline_state": state.get("pipeline_state", "IDLE"),
            "muted": state.get("muted", False),
            "uptime_seconds": state.get("uptime_seconds", 0),
            "models": {
                "fast": cfg.claude_model_fast,
                "smart": cfg.claude_model_smart,
            },
            "spend": costs.get_spend_summary(cfg.daily_budget_usd, cfg.monthly_budget_usd),
            "conversations": events.get_recent_conversations(50),
            "pending_confirm": _pending_confirm(),
        })

    @app.route("/api/metrics")
    def api_metrics():  # noqa: ANN202
        uptime = int(time.time() - _START_TIME)
        hours, rem = divmod(uptime, 3600)
        minutes = rem // 60
        return jsonify({
            "uptime_seconds": uptime,
            "uptime_display": f"{hours}h {minutes}m" if hours else f"{minutes}m",
            "queries_today": costs.get_daily_query_count(),
            "tools_today": costs.get_daily_tool_count(),
        })

    @app.route("/api/improvement/turns")
    def api_improvement_turns():  # noqa: ANN202
        from improvement.stats import fetch_turns

        limit = request.args.get("limit", 50, type=int)
        session_id = request.args.get("session_id") or None
        return jsonify({"turns": fetch_turns(limit=limit, session_id=session_id)})

    @app.route("/api/improvement/events")
    def api_improvement_events():  # noqa: ANN202
        from improvement.stats import fetch_events

        turn_id = request.args.get("turn_id", "").strip()
        if not turn_id:
            return jsonify({"error": "turn_id required"}), 400
        return jsonify({"events": fetch_events(turn_id=turn_id)})

    @app.route("/api/improvement/stats")
    def api_improvement_stats():  # noqa: ANN202
        from improvement.stats import compute_stats

        return jsonify(compute_stats())

    @app.route("/api/improvement/suggestions")
    def api_improvement_suggestions():  # noqa: ANN202
        from improvement.reflect import fetch_suggestions

        status = request.args.get("status", "pending")
        limit = request.args.get("limit", 20, type=int)
        return jsonify({"suggestions": fetch_suggestions(status=status, limit=limit)})

    @app.route("/api/improvement/suggestions/<suggestion_id>/accept", methods=["POST"])
    def api_improvement_suggestion_accept(suggestion_id: str):  # noqa: ANN202
        from improvement.reflect import accept_suggestion

        result = accept_suggestion(suggestion_id)
        return jsonify(result), (200 if result.get("ok") else 404)

    @app.route("/api/improvement/suggestions/<suggestion_id>/dismiss", methods=["POST"])
    def api_improvement_suggestion_dismiss(suggestion_id: str):  # noqa: ANN202
        from improvement.reflect import update_suggestion_status

        ok = update_suggestion_status(suggestion_id, "dismissed")
        return jsonify({"ok": ok}), (200 if ok else 404)

    @app.route("/api/improvement/suggestions/generate", methods=["POST"])
    def api_improvement_suggestions_generate():  # noqa: ANN202
        from improvement.reflect import run_reflection

        items = run_reflection()
        return jsonify({"ok": True, "count": len(items), "suggestions": items})

    @app.route("/api/github/issues")
    def api_github_issues():  # noqa: ANN202
        from tools.github_self import get_own_issues_results
        issues, err = get_own_issues_results(state="open")
        if err:
            return jsonify({"ok": False, "error": err, "issues": []})
        return jsonify({"ok": True, "issues": issues})

    # -- Sessions ----------------------------------------------------------
    @app.route("/api/sessions")
    def api_sessions():  # noqa: ANN202
        from orchestrator.runtime import get_session_store
        store = get_session_store()
        sessions = [s.to_dict() for s in store.all_active()]
        voice = [s for s in sessions if s["lane"] == "voice"]
        background = [s for s in sessions if s["lane"] == "background"]
        return jsonify({
            "ok": True,
            "sessions": sessions,
            "voice_count": len(voice),
            "background_count": len(background),
        })

    @app.route("/api/sessions/<session_id>")
    def api_session_detail(session_id: str):  # noqa: ANN202
        from orchestrator.runtime import get_session_store
        store = get_session_store()
        session = store.get(session_id)
        if session is None:
            return jsonify({"ok": False, "error": "Session not found"}), 404
        detail = session.to_dict()
        detail["turns"] = [
            {
                "id": t.id,
                "reply": t.reply[:200],
                "tools_used": t.tools_used,
                "model": t.model,
                "latency_ms": t.latency_ms,
            }
            for t in session.turns
        ]
        return jsonify({"ok": True, "session": detail})

    # -- Real-time event stream (SSE) --------------------------------------
    @app.route("/api/events")
    def api_events():  # noqa: ANN202
        def stream():  # noqa: ANN202
            client: queue.Queue = queue.Queue(maxsize=_SSE_QUEUE_MAX)
            with _sse_lock:
                _sse_clients.add(client)
            try:
                yield "retry: 3000\n\n"
                for msg in _initial_sse_payloads():
                    yield f"data: {msg}\n\n"
                while True:
                    try:
                        msg = client.get(timeout=_SSE_KEEPALIVE_SEC)
                        yield f"data: {msg}\n\n"
                    except queue.Empty:
                        yield ": keep-alive\n\n"
            finally:
                with _sse_lock:
                    _sse_clients.discard(client)

        return Response(
            stream(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # -- Settings + budgets -------------------------------------------------
    @app.route("/api/config", methods=["GET"])
    def api_config_get():  # noqa: ANN202
        return jsonify(Config.load().to_persisted_dict())

    @app.route("/api/config", methods=["POST"])
    def api_config_post():  # noqa: ANN202
        changes = request.get_json(silent=True) or {}
        cfg = Config.update_persisted(changes)
        tts_keys = {"tts_provider", "elevenlabs_voice_id", "elevenlabs_model_id", "cartesia_voice_id"}
        if tts_keys.intersection(changes):
            logger.debug(
                "🔊 TTS config updated live — provider=%s voice=%s",
                cfg.tts_provider,
                cfg.elevenlabs_voice_id,
            )
        return jsonify({"ok": True, "config": cfg.to_persisted_dict()})

    @app.route("/api/tts/voices", methods=["GET"])
    def api_tts_voices():  # noqa: ANN202
        from config import ELEVENLABS_VOICES

        cfg = Config.load()
        return jsonify({
            "voices": ELEVENLABS_VOICES,
            "selected": cfg.elevenlabs_voice_id,
            "provider": cfg.tts_provider,
        })

    @app.route("/api/tts/preview", methods=["POST"])
    def api_tts_preview():  # noqa: ANN202
        body = request.get_json(silent=True) or {}
        voice_id = (body.get("voice_id") or "").strip()
        text = (body.get("text") or "Hello, I'm Jarvis. How can I help you today?").strip()
        if not voice_id:
            return jsonify({"ok": False, "error": "voice_id is required"}), 400

        def _run_preview() -> None:
            try:
                from tts.router import speak_preview

                speak_preview(text, voice_id, provider="elevenlabs")
            except Exception as exc:  # noqa: BLE001
                logger.debug("TTS preview failed: %s", exc, exc_info=True)

        threading.Thread(target=_run_preview, daemon=True, name="jarvis-tts-preview").start()
        return jsonify({"ok": True})

    @app.route("/api/login-item", methods=["GET"])
    def api_login_item_get():  # noqa: ANN202
        import platform

        from paths import launch_at_login_mode
        from tools.login_item import is_login_item_enabled

        supported = platform.system() == "Darwin"
        return jsonify({
            "supported": supported,
            "enabled": is_login_item_enabled() if supported else False,
            "mode": launch_at_login_mode() if supported else None,
        })

    @app.route("/api/login-item", methods=["POST"])
    def api_login_item_post():  # noqa: ANN202
        import platform

        from tools.login_item import disable_login_item, enable_login_item, is_login_item_enabled

        if platform.system() != "Darwin":
            return jsonify({"ok": False, "error": "Launch at login is macOS only."}), 400

        body = request.get_json(silent=True) or {}
        if "enabled" not in body:
            return jsonify({"ok": False, "error": "enabled is required"}), 400

        enabled = bool(body["enabled"])
        result = enable_login_item() if enabled else disable_login_item()
        if "macOS only" in result:
            return jsonify({"ok": False, "error": result, "enabled": False}), 400
        if result.lower().startswith("could not"):
            return jsonify({"ok": False, "error": result, "enabled": is_login_item_enabled()}), 500

        return jsonify({
            "ok": True,
            "enabled": is_login_item_enabled(),
            "result": result,
        })

    @app.route("/api/music/now-playing")
    def api_music_now_playing():  # noqa: ANN202
        import platform

        from tools.music import get_now_playing

        supported = platform.system() in ("Darwin", "Windows")
        macos = platform.system() == "Darwin"
        return jsonify({
            "supported": supported,
            "macos": macos,
            "now_playing": get_now_playing(),
        })

    # -- Tools: list + run directly from the dashboard ---------------------
    @app.route("/api/tools")
    def api_tools():  # noqa: ANN202
        from tools.registry import (
            AUTO_ALLOW_TOOLS,
            CONFIRM_REQUIRED_TOOLS,
            MODERATE_TOOLS,
            READ_ONLY_TOOLS,
            TOOL_DEFINITIONS,
        )

        def tier(name: str) -> str:
            if name in CONFIRM_REQUIRED_TOOLS:
                return "high"
            if name in MODERATE_TOOLS:
                return "moderate"
            if name in READ_ONLY_TOOLS:
                return "read"
            if name in AUTO_ALLOW_TOOLS:
                return "write"
            return "write"

        tools = [{**defn, "tier": tier(defn["name"])} for defn in TOOL_DEFINITIONS]
        return jsonify({"tools": tools})

    @app.route("/api/tools/run", methods=["POST"])
    def api_tools_run():  # noqa: ANN202
        body = request.get_json(silent=True) or {}
        name = (body.get("name") or "").strip()
        inputs = body.get("inputs") or {}
        if not name:
            return jsonify({"ok": False, "error": "name is required"}), 400
        if not isinstance(inputs, dict):
            return jsonify({"ok": False, "error": "inputs must be an object"}), 400

        from dashboard.tools_run_confirm import consume, create_pending
        from tools.registry import DASHBOARD_CONFIRM_TOOLS, TOOL_DISPATCH, dispatch_tool

        if name not in TOOL_DISPATCH:
            return jsonify({"ok": False, "error": f"Unknown tool: {name}"}), 404

        confirm_id = (body.get("confirm_id") or "").strip()
        confirmed = bool(body.get("confirmed"))

        if name in DASHBOARD_CONFIRM_TOOLS:
            if confirm_id and confirmed:
                entry = consume(confirm_id)
                if entry is None:
                    return jsonify({"ok": False, "error": "confirm_id expired or invalid"}), 400
                if entry["tool"] != name or entry["inputs"] != inputs:
                    return jsonify({"ok": False, "error": "confirm mismatch"}), 400
            elif not confirm_id:
                cid = create_pending(name, inputs)
                return jsonify({
                    "ok": False,
                    "confirm_required": True,
                    "confirm_id": cid,
                    "tool": name,
                    "inputs": inputs,
                })
            else:
                return jsonify({"ok": False, "error": "confirmed must be true to execute"}), 400

        result = dispatch_tool(name, inputs, confirm=False)
        failed = result.startswith("Tool error") or result.startswith("Unknown tool")
        try:
            costs.log_tool_run(name, inputs, result, ok=not failed)
        except Exception:  # noqa: BLE001
            logger.debug("tool run log failed", exc_info=True)
        try:
            from orchestrator.runtime import get_bus

            get_bus().emit("tool.run", name=name, ok=not failed)
        except Exception:  # noqa: BLE001
            logger.debug("tool.run bus emit failed", exc_info=True)
        return jsonify({"ok": not failed, "name": name, "result": result})

    # -- Memory: variables --------------------------------------------------
    @app.route("/api/variables", methods=["GET"])
    def api_variables_get():  # noqa: ANN202
        return jsonify(variables.get_all_variables())

    @app.route("/api/variables", methods=["POST"])
    def api_variables_post():  # noqa: ANN202
        body = request.get_json(silent=True) or {}
        key = (body.get("key") or "").strip()
        if not key:
            return jsonify({"ok": False, "error": "key is required"}), 400
        variables.set_variable(key, str(body.get("value", "")))
        return jsonify({"ok": True})

    @app.route("/api/variables/<key>", methods=["DELETE"])
    def api_variables_delete(key: str):  # noqa: ANN202
        removed = variables.delete_variable(key)
        return jsonify({"ok": removed})

    # -- Memory: notes ------------------------------------------------------
    @app.route("/api/notes", methods=["GET"])
    def api_notes_get():  # noqa: ANN202
        return jsonify({"notes": knowledge.list_notes()})

    @app.route("/api/notes/<title>", methods=["GET"])
    def api_note_read(title: str):  # noqa: ANN202
        content = knowledge.read_note(title)
        if content is None:
            return jsonify({"ok": False, "error": "not found"}), 404
        return jsonify({"ok": True, "title": title, "content": content})

    @app.route("/api/notes", methods=["POST"])
    def api_note_write():  # noqa: ANN202
        body = request.get_json(silent=True) or {}
        title = (body.get("title") or "").strip()
        if not title:
            return jsonify({"ok": False, "error": "title is required"}), 400
        knowledge.write_note(title, str(body.get("content", "")))
        return jsonify({"ok": True})

    @app.route("/api/notes/<title>", methods=["DELETE"])
    def api_note_delete(title: str):  # noqa: ANN202
        removed = knowledge.delete_note(title)
        return jsonify({"ok": removed})

    @app.route("/api/contacts")
    def api_contacts():  # noqa: ANN202
        """Return the user's Google Contacts for the dashboard."""
        try:
            from tools.google_contacts import list_contacts_full

            contacts = list_contacts_full(count=200)
            return jsonify({"contacts": contacts})
        except Exception as exc:  # noqa: BLE001
            return jsonify({"contacts": [], "error": str(exc)})

    @app.route("/api/email/unread")
    def api_email_unread():  # noqa: ANN202
        """Return structured unread inbox messages for the email triage view."""
        try:
            from tools.google_gmail import fetch_unread_emails

            limit = int(request.args.get("limit") or 20)
            emails = fetch_unread_emails(max_results=max(1, min(limit, 20)))
            return jsonify({"ok": True, "emails": emails, "count": len(emails)})
        except Exception as exc:  # noqa: BLE001
            logger.debug("email unread fetch failed", exc_info=True)
            return jsonify({"ok": False, "emails": [], "error": str(exc)})

    @app.route("/api/email/draft-reply", methods=["POST"])
    def api_email_draft_reply():  # noqa: ANN202
        """Draft a reply body for one unread message using Claude."""
        body = request.get_json(silent=True) or {}
        message_id = (body.get("message_id") or "").strip()
        if not message_id:
            return jsonify({"ok": False, "error": "message_id is required"}), 400

        cfg = Config.load()
        if not cfg.anthropic_api_key:
            return jsonify({"ok": False, "error": "ANTHROPIC_API_KEY is not configured"}), 400

        try:
            from tools.google_gmail import (
                draft_email_reply,
                fetch_thread_context,
                fetch_unread_emails,
                reply_subject,
            )

            email = None
            for item in fetch_unread_emails(max_results=20):
                if item.get("id") == message_id:
                    email = item
                    break
            if email is None:
                return jsonify({"ok": False, "error": "Message not found in unread inbox"}), 404

            thread_context = fetch_thread_context(email.get("thread_id", ""))
            draft_body = draft_email_reply(
                email,
                thread_context=thread_context,
                model=cfg.claude_model_fast,
                api_key=cfg.anthropic_api_key,
            )
            return jsonify({
                "ok": True,
                "to": email.get("from_email") or "",
                "subject": reply_subject(email.get("subject", "")),
                "body": draft_body,
                "from": email.get("from", ""),
                "message_id": message_id,
            })
        except Exception as exc:  # noqa: BLE001
            logger.error("email draft failed: %s", exc, exc_info=True)
            return jsonify({"ok": False, "error": str(exc)}), 500

    @app.route("/api/calendar/day")
    def api_calendar_day():  # noqa: ANN202
        """Return structured calendar events for one day."""
        from datetime import datetime

        date_str = (request.args.get("date") or "").strip()
        if not date_str:
            date_str = datetime.now().astimezone().date().isoformat()
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return jsonify({"ok": False, "error": "date must be YYYY-MM-DD"}), 400

        try:
            from tools.google_calendar import fetch_calendar_day

            day = fetch_calendar_day(date_str)
            return jsonify({"ok": True, **day, "count": len(day["events"])})
        except Exception as exc:  # noqa: BLE001
            logger.debug("calendar day fetch failed", exc_info=True)
            return jsonify({"ok": False, "error": str(exc), "date": date_str, "events": []})

    # -- Semantic memory ----------------------------------------------------
    @app.route("/api/memory/info")
    def api_memory_info():  # noqa: ANN202
        from memory import store

        root = store.resolve_memory_root()
        profile = store.profile_path()
        return jsonify({
            "root": str(root),
            "notes_dir": str(store.notes_dir()),
            "profile_exists": profile.is_file(),
            "note_count": len(knowledge.list_notes()),
        })

    @app.route("/api/memory/search")
    def api_memory_search():  # noqa: ANN202
        from memory import semantic

        query = (request.args.get("q") or "").strip()
        if not query:
            return jsonify({"ok": False, "error": "q is required"}), 400
        limit = int(request.args.get("limit") or 8)
        hits = semantic.search(query, top_k=max(1, min(limit, 20)))
        return jsonify({"ok": True, "query": query, "hits": hits})

    @app.route("/api/memory/reindex", methods=["POST"])
    def api_memory_reindex():  # noqa: ANN202
        from memory import semantic

        count = semantic.reindex_all()
        return jsonify({"ok": True, "chunks": count})

    # -- Text message into the pipeline (no STT/TTS) ------------------------
    @app.route("/api/message", methods=["POST"])
    def api_message():  # noqa: ANN202
        body = request.get_json(silent=True) or {}
        text = (body.get("text") or "").strip()
        if not text:
            return jsonify({"ok": False, "error": "text is required"}), 400
        # Route through the shared orchestrator so dashboard + voice queue
        # together instead of racing. speak=False: the reply renders on screen.
        import pipeline
        from orchestrator.runtime import get_orchestrator
        from orchestrator.types import Command, CommandSource

        orch = get_orchestrator()
        sub = orch.submit(Command(text=text, source=CommandSource.DASHBOARD, speak=False))
        if not sub.accepted:
            return jsonify({"ok": False, "busy": True, "reply": pipeline.BUSY_MESSAGE}), 409

        job = orch.wait(sub.job_id, timeout=180.0)
        if job is None:
            return jsonify({"ok": False, "error": "timeout"}), 504
        if job.error == "busy":
            return jsonify({"ok": False, "busy": True, "reply": job.reply or pipeline.BUSY_MESSAGE}), 409

        reply = job.reply
        if job.warning:
            reply = job.warning + " " + reply
        return jsonify({
            "ok": True,
            "reply": reply,
            "model": job.model,
            "latency_ms": job.latency_ms,
            "cost": job.cost,
            "capped": job.capped,
        })

    @app.route("/api/interrupt", methods=["POST"])
    def api_interrupt():  # noqa: ANN202
        from orchestrator.runtime import get_orchestrator

        get_orchestrator().cancel_current()
        return jsonify({"ok": True})

    @app.route("/api/confirm/respond", methods=["POST"])
    def api_confirm_respond():  # noqa: ANN202
        from tools import confirm as tool_confirm
        body = request.get_json(silent=True) or {}
        confirm_id = (body.get("id") or "").strip()
        if not confirm_id:
            return jsonify({"ok": False, "error": "id is required"}), 400
        allow = bool(body.get("allow"))
        resolved = tool_confirm.respond(confirm_id, allow)
        if not resolved:
            return jsonify({"ok": False, "error": "no matching pending confirm"}), 404
        return jsonify({"ok": True, "allow": allow})

    @app.route("/api/plugins")
    def api_plugins_list():  # noqa: ANN202
        return jsonify({"plugins": list_plugin_manifests()})

    @app.route("/hooks/<plugin_id>", methods=["POST"])
    def webhook_handler(plugin_id: str):  # noqa: ANN202
        from plugins.loader import discover_plugins
        from orchestrator.runtime import get_orchestrator
        from orchestrator.types import Command, CommandSource

        plugins = discover_plugins()
        matched = None
        target = f"hooks/{plugin_id.strip('/')}"
        for plugin in plugins:
            trigger = plugin.get("trigger", {})
            if trigger.get("type") != "webhook":
                continue
            path = (trigger.get("path") or "").strip("/")
            if path == target or plugin.get("_slug") == plugin_id or plugin.get("name") == plugin_id:
                matched = plugin
                break
        if matched is None:
            return jsonify({"error": f"No plugin matches webhook '{plugin_id}'"}), 404
        if not matched.get("enabled", True):
            return jsonify({"error": "Plugin is disabled"}), 403

        payload = request.get_json(silent=True) or {}
        prompt = (matched.get("prompt") or "").strip()
        full_prompt = f"{prompt}\n\nWebhook payload: {json.dumps(payload)[:2000]}"
        orch = get_orchestrator()
        sub = orch.submit(Command(text=full_prompt, source=CommandSource.WEBHOOK, speak=False))
        if not sub.accepted:
            return jsonify({"error": "Queue full"}), 429
        return jsonify({"ok": True, "job_id": sub.job_id})

    return app


def run_dashboard() -> None:
    """Blocking entry point — run on a daemon thread from main.py."""
    app = create_app()
    logger.info("📊 Dashboard on http://%s:%d", HOST, PORT)
    # threaded=True so polling + a long /api/message call don't block each other.
    app.run(host=HOST, port=PORT, threaded=True, debug=False, use_reloader=False)
