"""
dashboard/app.py — localhost Flask control panel for Jarvis.

Everything binds to 127.0.0.1 only. The app is intentionally tiny: one template,
one CSS file, vanilla JS polling /api/state every 2 s. No build step, no React,
no websockets.

Endpoints:
  GET  /                  → the dashboard page
  GET  /api/state         → pipeline state, mute, uptime, models, spend, log
  POST /api/config        → update editable settings/budgets (writes config.json)
  GET  /api/variables     → all memory variables
  POST /api/variables     → add/edit a variable {key, value}
  DELETE /api/variables/<key>
  GET  /api/notes         → list note titles
  GET  /api/notes/<title> → one note's content
  POST /api/notes         → create/overwrite {title, content}
  DELETE /api/notes/<title>
  POST /api/message       → {text} → run through the pipeline, return reply (text)
  POST /api/confirm/respond → {id, allow} → resolve pending tool confirm
"""

from __future__ import annotations

import logging

from flask import Flask, jsonify, request

import costs
import events
from config import Config
from memory import knowledge, variables

logger = logging.getLogger("jarvis.dashboard")

HOST = "127.0.0.1"
PORT = 7777


def _pending_confirm() -> dict | None:
    try:
        from tools import confirm as tool_confirm
        return tool_confirm.get_pending()
    except Exception:  # noqa: BLE001
        return None


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config["JSON_SORT_KEYS"] = False

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
        # Imported lazily so the dashboard module can be imported without the
        # heavy audio/LLM stack (e.g. in unit tests).
        import pipeline
        result = pipeline.process_query(text, Config.load())
        if result.get("busy"):
            return jsonify({
                "ok": False,
                "busy": True,
                "reply": result["reply"],
            }), 409
        reply = result["reply"]
        if result.get("warning"):
            reply = result["warning"] + " " + reply
        return jsonify({
            "ok": True,
            "reply": reply,
            "model": result.get("model"),
            "latency_ms": result.get("latency_ms"),
            "cost": result.get("cost"),
            "capped": result.get("capped", False),
        })

    @app.route("/api/interrupt", methods=["POST"])
    def api_interrupt():  # noqa: ANN202
        import pipeline
        pipeline.request_interrupt()
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
