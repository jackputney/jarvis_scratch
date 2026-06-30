"""onboarding.py — First-run setup wizard (PyQt6, 4 steps).

Collects the Anthropic API key (required) and optional Cartesia key, validates
the Anthropic key against the API, writes ~/.env (or Application Support/.env
when frozen), and marks onboarding complete.
"""

from __future__ import annotations

import logging
import os
import platform
from pathlib import Path

from paths import env_path, mark_onboarding_complete, needs_onboarding

logger = logging.getLogger("jarvis.onboarding")


def validate_anthropic_key_format(key: str) -> tuple[bool, str]:
    """Fast local validation before hitting the network."""
    val = key.strip()
    if not val:
        return False, "Anthropic API key is required."
    if _is_placeholder(val):
        return False, "Replace the placeholder with your real API key."
    if not val.startswith("sk-ant-"):
        return False, "Anthropic keys usually start with sk-ant-."
    return True, ""


def validate_anthropic_key(key: str, *, network: bool = True) -> tuple[bool, str]:
    """Validate format and optionally confirm the key with a minimal API call."""
    ok, msg = validate_anthropic_key_format(key)
    if not ok:
        return ok, msg
    if not network:
        return True, ""
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key.strip())
        client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"Key rejected by Anthropic: {exc}"


def write_env_file(
    anthropic_key: str,
    cartesia_key: str = "",
    *,
    target: Path | None = None,
) -> Path:
    """Write or update .env with the supplied keys."""
    path = target or env_path()
    lines: list[str] = []
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()

    updates = {
        "ANTHROPIC_API_KEY": anthropic_key.strip(),
    }
    if cartesia_key.strip():
        updates["CARTESIA_API_KEY"] = cartesia_key.strip()

    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(line)

    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")

    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    return path


def _is_placeholder(value: str) -> bool:
    lower = value.strip().lower()
    return lower.startswith("your_") or lower in {"", "sk-ant-your_anthropic_api_key_here"}


def run_onboarding_wizard(*, network_validation: bool = True) -> bool:
    """Show the 4-step PyQt6 wizard. Returns True when setup finished."""
    if not needs_onboarding():
        return True

    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (
        QApplication,
        QCheckBox,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QStackedWidget,
        QVBoxLayout,
        QWidget,
    )

    app = QApplication.instance() or QApplication([])

    anthropic_input = QLineEdit()
    anthropic_input.setEchoMode(QLineEdit.EchoMode.Password)
    anthropic_input.setPlaceholderText("sk-ant-…")

    cartesia_input = QLineEdit()
    cartesia_input.setEchoMode(QLineEdit.EchoMode.Password)
    cartesia_input.setPlaceholderText("Optional — leave blank for local TTS")

    developer_checkbox = QCheckBox(
        "I'm a developer working on Jarvis's own codebase (enables GitHub "
        "self-modify and self-update tools)"
    )
    developer_checkbox.setChecked(False)

    status_label = QLabel("")
    status_label.setWordWrap(True)
    status_label.setStyleSheet("color: #F87171;")

    stack = QStackedWidget()
    pages: list[QWidget] = []

    def _page(title: str, body: str, extra: QWidget | None = None) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        heading = QLabel(f"<h2>{title}</h2>")
        heading.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(heading)
        text = QLabel(body)
        text.setWordWrap(True)
        layout.addWidget(text)
        if extra is not None:
            layout.addWidget(extra)
        layout.addStretch()
        pages.append(w)
        stack.addWidget(w)
        return w

    storage_dir = env_path().parent
    if platform.system() == "Windows":
        storage_hint = f"%APPDATA%\\Jarvis ({storage_dir})"
    elif platform.system() == "Darwin":
        storage_hint = f"~/Library/Application Support/Jarvis ({storage_dir})"
    else:
        storage_hint = str(storage_dir)

    _page(
        "Welcome to Jarvis",
        "This quick setup collects your API keys and saves them locally on this computer "
        f"({storage_hint}). Nothing is sent anywhere except to Anthropic when you "
        "validate your key.",
    )

    anthropic_form = QWidget()
    form_layout = QFormLayout(anthropic_form)
    form_layout.addRow("Anthropic API key", anthropic_input)
    _page(
        "Anthropic API key",
        "Required. Jarvis uses Claude for replies. Get a key at console.anthropic.com.",
        anthropic_form,
    )

    cartesia_form = QWidget()
    cartesia_layout = QFormLayout(cartesia_form)
    cartesia_layout.addRow("Cartesia API key", cartesia_input)
    _page(
        "Voice (optional)",
        "Cartesia powers the premium British streaming voice. "
        "Skip this to use local TTS instead.",
        cartesia_form,
    )

    _page(
        "Developer access",
        "By default Jarvis cannot modify its own codebase or push updates from "
        "GitHub. Only enable this if you're actively developing Jarvis itself.",
        developer_checkbox,
    )

    summary = QLabel("")
    summary.setWordWrap(True)
    _page("Ready", "Review and click Finish to save your settings.", summary)

    window = QWidget()
    window.setWindowTitle("Jarvis Setup")
    window.resize(520, 360)
    root = QVBoxLayout(window)
    root.addWidget(stack)
    root.addWidget(status_label)

    btn_row = QHBoxLayout()
    back_btn = QPushButton("Back")
    next_btn = QPushButton("Next")
    finish_btn = QPushButton("Finish")
    cancel_btn = QPushButton("Cancel")
    finish_btn.hide()
    btn_row.addWidget(cancel_btn)
    btn_row.addStretch()
    btn_row.addWidget(back_btn)
    btn_row.addWidget(next_btn)
    btn_row.addWidget(finish_btn)
    root.addLayout(btn_row)

    result = {"ok": False}

    def _refresh_nav() -> None:
        idx = stack.currentIndex()
        back_btn.setEnabled(idx > 0)
        on_last = idx == stack.count() - 1
        next_btn.setVisible(not on_last)
        finish_btn.setVisible(on_last)
        if on_last:
            dev_line = (
                "Developer mode: ON — GitHub self-modify and self-update tools enabled."
                if developer_checkbox.isChecked()
                else "Developer mode: OFF — Jarvis cannot modify its own code or self-update."
            )
            summary.setText(
                "Your Anthropic key will be saved to:\n"
                f"{env_path()}\n\n"
                f"{dev_line}\n\n"
                "Jarvis will register the global hotkey (Ctrl+Shift+Space) on launch."
            )

    def _show_error(msg: str) -> None:
        status_label.setText(msg)

    def _validate_step() -> bool:
        status_label.clear()
        idx = stack.currentIndex()
        if idx == 1:
            ok, msg = validate_anthropic_key(
                anthropic_input.text(),
                network=network_validation,
            )
            if not ok:
                _show_error(msg)
                return False
        return True

    def _go_next() -> None:
        if not _validate_step():
            return
        stack.setCurrentIndex(stack.currentIndex() + 1)
        _refresh_nav()

    def _go_back() -> None:
        status_label.clear()
        stack.setCurrentIndex(max(0, stack.currentIndex() - 1))
        _refresh_nav()

    def _finish() -> None:
        if not _validate_step():
            return
        write_env_file(anthropic_input.text(), cartesia_input.text())
        mark_onboarding_complete()
        os.environ["ANTHROPIC_API_KEY"] = anthropic_input.text().strip()
        cartesia = cartesia_input.text().strip()
        if cartesia:
            os.environ["CARTESIA_API_KEY"] = cartesia
        try:
            from config import Config

            Config.update_persisted({"developer_mode": developer_checkbox.isChecked()})
        except Exception:  # noqa: BLE001
            logger.warning("Could not persist developer_mode setting", exc_info=True)
        logger.info("✅ Onboarding complete — keys saved to %s", env_path())
        result["ok"] = True
        window.close()

    def _cancel() -> None:
        if QMessageBox.question(
            window,
            "Cancel setup?",
            "Jarvis needs an Anthropic API key before it can run.",
        ) == QMessageBox.StandardButton.Yes:
            result["ok"] = False
            window.close()

    next_btn.clicked.connect(_go_next)
    back_btn.clicked.connect(_go_back)
    finish_btn.clicked.connect(_finish)
    cancel_btn.clicked.connect(_cancel)
    _refresh_nav()
    window.show()
    app.exec()
    return result["ok"]
