"""
dashboard/app.py — localhost Flask control panel for Jarvis.

Everything binds to 127.0.0.1 only. The app is intentionally tiny: one template,
one CSS file, vanilla JS. No build step, no React. State pushes over a Server-Sent
Events stream (/api/events) fed by the orchestrator bus; a slow poll is the
fallback. Text messages and Stop go through the shared orchestrator queue so the
dashboard and the voice loop never race.

Endpoints:
  GET  /                  → the dashboard page
  GET  /api/state         → pipeline state, mute, uptime, models, spend, log
  GET  /api/events        → Server-Sent Events stream of job/pipeline events
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
"""

from __future__ import annotations

import json
import logging
import queue
import threading

from flask import Flask, Response, jsonify, request

import costs
import events
from config import Config
from memory import knowledge, variables

logger = logging.getLogger("jarvis.dashboard")

HOST = "127.0.0.1"
PORT = 7777

# -- Server-Sent Events fan-out ---------------------------------------------
# The orchestrator emits job/state events on the shared bus; we mirror them to
# every connected browser so the UI updates instantly instead of polling hard.
_sse_clients: set[queue.Queue] = set()
_sse_lock = threading.Lock()
_sse_subscribed = False
_SSE_KEEPALIVE_SEC = 15.0
_SSE_QUEUE_MAX = 100


def _broadcast(event: str, payload: dict) -> None:
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


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config["JSON_SORT_KEYS"] = False
    _ensure_bus_subscription()

    # -- Page ---------------------------------------------------------------
    @app.route("/")
    def index():  # noqa: ANN202
        from flask import render_template
        return render_template("index.html")

    # -- State (polled every 2s) -------------------------------------------
    @app.route("/api/state")
    def api_state():  # noqa: ANN202
        cfg = Config.load()
        state = events.get_state()
        return jsonify({
            "pipeline_state": state["pipeline_state"],
            "muted": state["muted"],
            "uptime_seconds": state["uptime_seconds"],
            "models": {
                "fast": cfg.claude_model_fast,
                "smart": cfg.claude_model_smart,
            },
            "spend": costs.get_spend_summary(cfg.daily_budget_usd, cfg.monthly_budget_usd),
            "conversations": events.get_recent_conversations(50),
            "pending_confirm": _pending_confirm(),
        })

    # -- Real-time event stream (SSE) --------------------------------------
    @app.route("/api/events")
    def api_events():  # noqa: ANN202
        def stream():  # noqa: ANN202
            client: queue.Queue = queue.Queue(maxsize=_SSE_QUEUE_MAX)
            with _sse_lock:
                _sse_clients.add(client)
            try:
                yield "retry: 3000\n\n"
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
        return jsonify({"ok": True, "config": cfg.to_persisted_dict()})

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

    return app


def run_dashboard() -> None:
    """Blocking entry point — run on a daemon thread from main.py."""
    app = create_app()
    logger.info("📊 Dashboard on http://%s:%d", HOST, PORT)
    # threaded=True so polling + a long /api/message call don't block each other.
    app.run(host=HOST, port=PORT, threaded=True, debug=False, use_reloader=False)
