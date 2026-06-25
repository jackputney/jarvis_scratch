"""Tests for tools/dev_log.py — Google Docs-backed Jarvis Dev Log."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from config import Config


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

FAKE_DOC_ID = "18OUXDja6GbV99dB_sv2iGlsLJTCqg3AQ95kvQbazQyc"

_LOG_SECTION = "## LOG\n---\n\n### 2026-06-25 | Jack's Claude\n- Ran tests\n---\n\n### 2026-06-24 | Oliver's Claude\n- Fixed Windows TTS\n---\n\n### 2026-06-23 | Jack's Claude\n- Initial setup\n---\n"

_FAKE_DOC = {
    "body": {
        "content": [
            {
                "paragraph": {
                    "elements": [{"textRun": {"content": "Jarvis Dev Log\n"}}]
                }
            },
            {
                "paragraph": {
                    "elements": [{"textRun": {"content": "## LOG\n"}}]
                }
            },
            {
                "paragraph": {
                    "elements": [{"textRun": {"content": "---\n"}}]
                }
            },
            {
                "paragraph": {
                    "elements": [{"textRun": {"content": "### 2026-06-25 | Jack's Claude\n"}}]
                }
            },
            {
                "paragraph": {
                    "elements": [{"textRun": {"content": "- Ran tests\n"}}]
                }
            },
            {
                "paragraph": {
                    "elements": [{"textRun": {"content": "---\n"}}]
                }
            },
            {
                "paragraph": {
                    "elements": [{"textRun": {"content": "### 2026-06-24 | Oliver's Claude\n"}}]
                }
            },
            {
                "paragraph": {
                    "elements": [{"textRun": {"content": "- Fixed Windows TTS\n"}}]
                }
            },
            {
                "paragraph": {
                    "elements": [{"textRun": {"content": "---\n"}}]
                }
            },
            {
                "paragraph": {
                    "elements": [{"textRun": {"content": "### 2026-06-23 | Jack's Claude\n"}}]
                }
            },
            {
                "paragraph": {
                    "elements": [{"textRun": {"content": "- Initial setup\n"}}]
                }
            },
            {
                "paragraph": {
                    "elements": [{"textRun": {"content": "---\n"}}]
                }
            },
        ]
    }
}


def _make_docs_service(doc_content=None):
    """Return a mock Google Docs service."""
    svc = MagicMock()
    doc = doc_content if doc_content is not None else _FAKE_DOC
    svc.documents.return_value.get.return_value.execute.return_value = doc
    svc.documents.return_value.batchUpdate.return_value.execute.return_value = {}
    return svc


# ---------------------------------------------------------------------------
# read_dev_log
# ---------------------------------------------------------------------------

class TestReadDevLog:
    def test_returns_string_content(self, monkeypatch):
        from tools import dev_log

        svc = _make_docs_service()
        monkeypatch.setattr(dev_log, "_get_docs_service", lambda: svc)
        monkeypatch.setattr(dev_log, "_doc_id", lambda: FAKE_DOC_ID)

        result = dev_log.read_dev_log()

        assert isinstance(result, str)
        assert len(result) > 0

    def test_content_contains_log_entries(self, monkeypatch):
        from tools import dev_log

        svc = _make_docs_service()
        monkeypatch.setattr(dev_log, "_get_docs_service", lambda: svc)
        monkeypatch.setattr(dev_log, "_doc_id", lambda: FAKE_DOC_ID)

        result = dev_log.read_dev_log()

        assert "Jack's Claude" in result
        assert "Oliver's Claude" in result

    def test_missing_doc_id_returns_error(self, monkeypatch):
        from tools import dev_log

        monkeypatch.setattr(dev_log, "_doc_id", lambda: "")

        result = dev_log.read_dev_log()

        assert "dev_log_doc_id" in result or "not configured" in result.lower()

    def test_api_error_returns_graceful_message(self, monkeypatch):
        from tools import dev_log

        svc = MagicMock()
        svc.documents.return_value.get.return_value.execute.side_effect = Exception("403 Forbidden")
        monkeypatch.setattr(dev_log, "_get_docs_service", lambda: svc)
        monkeypatch.setattr(dev_log, "_doc_id", lambda: FAKE_DOC_ID)

        result = dev_log.read_dev_log()

        assert "error" in result.lower() or "could not" in result.lower()


# ---------------------------------------------------------------------------
# append_dev_log_entry
# ---------------------------------------------------------------------------

class TestAppendDevLogEntry:
    def test_inserts_after_log_section_marker(self, monkeypatch):
        from tools import dev_log

        svc = _make_docs_service()
        monkeypatch.setattr(dev_log, "_get_docs_service", lambda: svc)
        monkeypatch.setattr(dev_log, "_doc_id", lambda: FAKE_DOC_ID)

        dev_log.append_dev_log_entry("Sprint 7 complete", author="Jack's Claude")

        svc.documents.return_value.batchUpdate.assert_called_once()
        call_args = svc.documents.return_value.batchUpdate.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body") or call_args[0][1]
        requests = body["requests"]
        assert any("insertText" in r for r in requests)

    def test_entry_format_contains_author_and_summary(self, monkeypatch):
        from tools import dev_log

        inserted_texts: list[str] = []

        def capture_batch(documentId, body):  # noqa: N803
            for req in body.get("requests", []):
                if "insertText" in req:
                    inserted_texts.append(req["insertText"]["text"])
            mock = MagicMock()
            mock.execute.return_value = {}
            return mock

        svc = _make_docs_service()
        svc.documents.return_value.batchUpdate.side_effect = capture_batch
        monkeypatch.setattr(dev_log, "_get_docs_service", lambda: svc)
        monkeypatch.setattr(dev_log, "_doc_id", lambda: FAKE_DOC_ID)

        dev_log.append_dev_log_entry("Fixed the widget\nAdded new test", author="Jack's Claude")

        combined = "\n".join(inserted_texts)
        assert "Jack's Claude" in combined
        assert "Fixed the widget" in combined

    def test_entry_contains_separator(self, monkeypatch):
        from tools import dev_log

        inserted_texts: list[str] = []

        def capture_batch(documentId, body):  # noqa: N803
            for req in body.get("requests", []):
                if "insertText" in req:
                    inserted_texts.append(req["insertText"]["text"])
            mock = MagicMock()
            mock.execute.return_value = {}
            return mock

        svc = _make_docs_service()
        svc.documents.return_value.batchUpdate.side_effect = capture_batch
        monkeypatch.setattr(dev_log, "_get_docs_service", lambda: svc)
        monkeypatch.setattr(dev_log, "_doc_id", lambda: FAKE_DOC_ID)

        dev_log.append_dev_log_entry("test entry")

        combined = "\n".join(inserted_texts)
        assert "---" in combined

    def test_returns_confirmation_string(self, monkeypatch):
        from tools import dev_log

        svc = _make_docs_service()
        monkeypatch.setattr(dev_log, "_get_docs_service", lambda: svc)
        monkeypatch.setattr(dev_log, "_doc_id", lambda: FAKE_DOC_ID)

        result = dev_log.append_dev_log_entry("hello world")

        assert isinstance(result, str)
        assert len(result) > 0

    def test_author_comes_from_config_when_not_specified(self, monkeypatch, temp_env):
        from tools import dev_log

        inserted_texts: list[str] = []

        def capture_batch(documentId, body):  # noqa: N803
            for req in body.get("requests", []):
                if "insertText" in req:
                    inserted_texts.append(req["insertText"]["text"])
            mock = MagicMock()
            mock.execute.return_value = {}
            return mock

        svc = _make_docs_service()
        svc.documents.return_value.batchUpdate.side_effect = capture_batch
        monkeypatch.setattr(dev_log, "_get_docs_service", lambda: svc)
        monkeypatch.setattr(dev_log, "_doc_id", lambda: FAKE_DOC_ID)
        monkeypatch.setattr(dev_log, "_author", lambda: "Oliver's Claude")

        dev_log.append_dev_log_entry("Oliver's entry")

        combined = "\n".join(inserted_texts)
        assert "Oliver's Claude" in combined

    def test_missing_doc_id_returns_error(self, monkeypatch):
        from tools import dev_log

        monkeypatch.setattr(dev_log, "_doc_id", lambda: "")

        result = dev_log.append_dev_log_entry("something")

        assert "not configured" in result.lower() or "dev_log_doc_id" in result


# ---------------------------------------------------------------------------
# get_dev_log_summary
# ---------------------------------------------------------------------------

class TestGetDevLogSummary:
    def test_returns_at_most_three_entries(self, monkeypatch):
        from tools import dev_log

        svc = _make_docs_service()
        monkeypatch.setattr(dev_log, "_get_docs_service", lambda: svc)
        monkeypatch.setattr(dev_log, "_doc_id", lambda: FAKE_DOC_ID)

        result = dev_log.get_dev_log_summary()

        entry_count = result.count("---")
        assert entry_count <= 4  # at most 3 entries + trailing separator

    def test_summary_is_string(self, monkeypatch):
        from tools import dev_log

        svc = _make_docs_service()
        monkeypatch.setattr(dev_log, "_get_docs_service", lambda: svc)
        monkeypatch.setattr(dev_log, "_doc_id", lambda: FAKE_DOC_ID)

        result = dev_log.get_dev_log_summary()

        assert isinstance(result, str)

    def test_missing_doc_id_returns_error(self, monkeypatch):
        from tools import dev_log

        monkeypatch.setattr(dev_log, "_doc_id", lambda: "")

        result = dev_log.get_dev_log_summary()

        assert "not configured" in result.lower() or "dev_log_doc_id" in result


# ---------------------------------------------------------------------------
# _build_entry_text
# ---------------------------------------------------------------------------

class TestBuildEntryText:
    def test_single_line_summary(self):
        from tools.dev_log import _build_entry_text

        text = _build_entry_text("Sprint done", "Jack's Claude", "2026-06-25 14:00")
        assert "2026-06-25 14:00" in text
        assert "Jack's Claude" in text
        assert "- Sprint done" in text
        assert text.endswith("---\n")

    def test_multiline_summary_each_prefixed(self):
        from tools.dev_log import _build_entry_text

        text = _build_entry_text("Line one\nLine two", "Jack's Claude", "2026-06-25 14:00")
        assert "- Line one" in text
        assert "- Line two" in text

    def test_already_bulleted_lines_not_double_prefixed(self):
        from tools.dev_log import _build_entry_text

        text = _build_entry_text("- Already a bullet\n- Another one", "Jack's Claude", "2026-06-25 14:00")
        assert text.count("- Already a bullet") == 1
        assert text.count("--") == 0 or "---" in text  # only the separator

    def test_empty_summary_still_produces_header(self):
        from tools.dev_log import _build_entry_text

        text = _build_entry_text("", "Jack's Claude", "2026-06-25 14:00")
        assert "Jack's Claude" in text
        assert "---" in text
