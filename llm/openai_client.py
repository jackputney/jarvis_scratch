"""
llm/openai_client.py — OpenAI adapter that quacks like anthropic.Anthropic.

Exposes `.messages.stream(**kwargs)` / `.messages.create(**kwargs)` taking
Anthropic-format args (model, max_tokens, system, tools, messages) and returning
Anthropic-shaped responses, so pipeline._create_claude_message works unchanged.
The `openai` SDK is imported lazily so this module loads without it installed.
"""

from __future__ import annotations

import json
from typing import Any

from llm.base import LLMResponse, TextBlock, ToolUseBlock, Usage, iter_blocks, system_to_text


def to_openai_tools(tools: list[dict] | None) -> list[dict] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


def to_openai_messages(system: Any, messages: list[dict]) -> list[dict]:
    """Translate Anthropic system + messages into OpenAI chat messages."""
    out: list[dict] = []
    sys_text = system_to_text(system)
    if sys_text:
        out.append({"role": "system", "content": sys_text})

    for msg in messages:
        role = msg["role"]
        text_parts: list[str] = []
        tool_calls: list[dict] = []
        tool_msgs: list[dict] = []

        for btype, block in iter_blocks(msg["content"]):
            if btype == "text":
                text_parts.append(block["text"] if isinstance(block, dict) else block.text)
            elif btype == "tool_use":
                bid = block["id"] if isinstance(block, dict) else block.id
                bname = block["name"] if isinstance(block, dict) else block.name
                binput = block["input"] if isinstance(block, dict) else block.input
                tool_calls.append({
                    "id": bid,
                    "type": "function",
                    "function": {"name": bname, "arguments": json.dumps(binput or {})},
                })
            elif btype == "tool_result":
                tool_msgs.append({
                    "role": "tool",
                    "tool_call_id": block.get("tool_use_id"),
                    "content": str(block.get("content", "")),
                })

        if role == "assistant":
            entry: dict[str, Any] = {"role": "assistant", "content": "".join(text_parts) or None}
            if tool_calls:
                entry["tool_calls"] = tool_calls
            out.append(entry)
        else:  # user
            if text_parts:
                out.append({"role": "user", "content": "".join(text_parts)})
            out.extend(tool_msgs)
    return out


class _OpenAIStream:
    """Wraps an OpenAI streaming response in the anthropic stream interface."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw
        self._text = ""
        self._tool_calls: dict[int, dict] = {}
        self._usage: Any = None

    def __enter__(self) -> "_OpenAIStream":
        return self

    def __exit__(self, *exc: Any) -> bool:
        try:
            self._raw.close()
        except Exception:  # noqa: BLE001
            pass
        return False

    @property
    def text_stream(self):
        for chunk in self._raw:
            choices = getattr(chunk, "choices", None)
            if choices:
                delta = choices[0].delta
                content = getattr(delta, "content", None)
                if content:
                    self._text += content
                    yield content
                for tcd in (getattr(delta, "tool_calls", None) or []):
                    slot = self._tool_calls.setdefault(
                        tcd.index, {"id": None, "name": "", "args": ""}
                    )
                    if getattr(tcd, "id", None):
                        slot["id"] = tcd.id
                    fn = getattr(tcd, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            slot["name"] = fn.name
                        if getattr(fn, "arguments", None):
                            slot["args"] += fn.arguments
            if getattr(chunk, "usage", None):
                self._usage = chunk.usage

    def get_final_message(self) -> LLMResponse:
        content: list = []
        if self._text:
            content.append(TextBlock(text=self._text))
        for idx in sorted(self._tool_calls):
            slot = self._tool_calls[idx]
            try:
                parsed = json.loads(slot["args"]) if slot["args"] else {}
            except json.JSONDecodeError:
                parsed = {}
            content.append(
                ToolUseBlock(id=slot["id"] or f"call_{idx}", name=slot["name"], input=parsed)
            )
        u = self._usage
        usage = Usage(
            input_tokens=getattr(u, "prompt_tokens", 0) if u else 0,
            output_tokens=getattr(u, "completion_tokens", 0) if u else 0,
        )
        return LLMResponse(content=content, usage=usage)


class _OpenAIMessages:
    def __init__(self, parent: "OpenAIClient") -> None:
        self._parent = parent

    def stream(self, *, model: str, messages: list[dict], system: Any = None,
               tools: list[dict] | None = None, max_tokens: int = 1024, **_: Any) -> _OpenAIStream:
        client = self._parent._ensure()
        raw = client.chat.completions.create(
            model=model,
            messages=to_openai_messages(system, messages),
            tools=to_openai_tools(tools),
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        return _OpenAIStream(raw)

    def create(self, *, model: str, messages: list[dict], system: Any = None,
               tools: list[dict] | None = None, max_tokens: int = 1024, **_: Any) -> LLMResponse:
        client = self._parent._ensure()
        resp = client.chat.completions.create(
            model=model,
            messages=to_openai_messages(system, messages),
            tools=to_openai_tools(tools),
            max_tokens=max_tokens,
        )
        choice = resp.choices[0].message
        content: list = []
        if getattr(choice, "content", None):
            content.append(TextBlock(text=choice.content))
        for tc in (getattr(choice, "tool_calls", None) or []):
            try:
                parsed = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                parsed = {}
            content.append(ToolUseBlock(id=tc.id, name=tc.function.name, input=parsed))
        u = getattr(resp, "usage", None)
        usage = Usage(
            input_tokens=getattr(u, "prompt_tokens", 0) if u else 0,
            output_tokens=getattr(u, "completion_tokens", 0) if u else 0,
        )
        return LLMResponse(content=content, usage=usage)


class OpenAIClient:
    """Anthropic-shaped client backed by the OpenAI SDK (imported lazily)."""

    def __init__(self, api_key: str, timeout: float = 60.0) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._client: Any = None
        self.messages = _OpenAIMessages(self)

    def _ensure(self) -> Any:
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - env-dependent
                raise RuntimeError(
                    "OpenAI provider selected but the 'openai' package isn't installed. "
                    "Run: pip install openai"
                ) from exc
            self._client = OpenAI(api_key=self._api_key, timeout=self._timeout)
        return self._client
