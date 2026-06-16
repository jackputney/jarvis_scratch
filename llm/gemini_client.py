"""
llm/gemini_client.py — Google Gemini adapter that quacks like anthropic.Anthropic.

Uses the `google-genai` SDK (imported lazily). Translates Anthropic-format
requests to Gemini `contents` + a function-declaration tool config, and returns
Anthropic-shaped responses.

Mismatch handled here: Anthropic tool_result references a tool_use_id, but
Gemini function responses reference the function *name*. We track an id→name
map while walking the message list so tool results resolve to the right name.
The synthetic ids we mint for Gemini function calls (call_0, call_1, …) are only
used internally by the pipeline to pair tool_use with tool_result.
"""

from __future__ import annotations

from typing import Any

from llm.base import LLMResponse, TextBlock, ToolUseBlock, Usage, iter_blocks, system_to_text


def to_gemini_tools(types_mod: Any, tools: list[dict] | None) -> list | None:
    if not tools:
        return None
    declarations = [
        types_mod.FunctionDeclaration(
            name=t["name"],
            description=t.get("description", ""),
            parameters=t["input_schema"],
        )
        for t in tools
    ]
    return [types_mod.Tool(function_declarations=declarations)]


def to_gemini_contents(types_mod: Any, messages: list[dict]) -> list:
    """Translate Anthropic messages into Gemini Content objects.

    Gemini roles are 'user' and 'model'. Tool calls become function_call parts;
    tool results become function_response parts (resolved to the function name).
    """
    contents: list = []
    id_to_name: dict[str, str] = {}

    for msg in messages:
        role = "model" if msg["role"] == "assistant" else "user"
        parts: list = []

        for btype, block in iter_blocks(msg["content"]):
            if btype == "text":
                text = block["text"] if isinstance(block, dict) else block.text
                if text:
                    parts.append(types_mod.Part(text=text))
            elif btype == "tool_use":
                bid = block["id"] if isinstance(block, dict) else block.id
                bname = block["name"] if isinstance(block, dict) else block.name
                binput = block["input"] if isinstance(block, dict) else block.input
                id_to_name[bid] = bname
                parts.append(types_mod.Part(
                    function_call=types_mod.FunctionCall(name=bname, args=binput or {})
                ))
            elif btype == "tool_result":
                tuid = block.get("tool_use_id")
                name = id_to_name.get(tuid, tuid or "tool")
                parts.append(types_mod.Part(
                    function_response=types_mod.FunctionResponse(
                        name=name, response={"result": str(block.get("content", ""))}
                    )
                ))

        if parts:
            contents.append(types_mod.Content(role=role, parts=parts))
    return contents


def _parse_parts(candidate: Any) -> tuple[str, list[tuple[str, dict]]]:
    """Return (text, [(name, args), ...]) from a Gemini candidate."""
    text = ""
    calls: list[tuple[str, dict]] = []
    content = getattr(candidate, "content", None)
    for part in (getattr(content, "parts", None) or []):
        if getattr(part, "text", None):
            text += part.text
        fc = getattr(part, "function_call", None)
        if fc is not None:
            calls.append((fc.name, dict(fc.args or {})))
    return text, calls


class _GeminiStream:
    def __init__(self, raw: Any) -> None:
        self._raw = raw
        self._text = ""
        self._calls: list[tuple[str, dict]] = []
        self._usage: Any = None

    def __enter__(self) -> "_GeminiStream":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    @property
    def text_stream(self):
        for chunk in self._raw:
            candidates = getattr(chunk, "candidates", None) or []
            if candidates:
                text, calls = _parse_parts(candidates[0])
                if text:
                    self._text += text
                    yield text
                self._calls.extend(calls)
            if getattr(chunk, "usage_metadata", None):
                self._usage = chunk.usage_metadata

    def get_final_message(self) -> LLMResponse:
        content: list = []
        if self._text:
            content.append(TextBlock(text=self._text))
        for i, (name, args) in enumerate(self._calls):
            content.append(ToolUseBlock(id=f"call_{i}", name=name, input=args))
        u = self._usage
        usage = Usage(
            input_tokens=getattr(u, "prompt_token_count", 0) if u else 0,
            output_tokens=getattr(u, "candidates_token_count", 0) if u else 0,
        )
        return LLMResponse(content=content, usage=usage)


class _GeminiMessages:
    def __init__(self, parent: "GeminiClient") -> None:
        self._parent = parent

    def stream(self, *, model: str, messages: list[dict], system: Any = None,
               tools: list[dict] | None = None, max_tokens: int = 1024, **_: Any) -> _GeminiStream:
        client, types_mod = self._parent._ensure()
        config = types_mod.GenerateContentConfig(
            system_instruction=system_to_text(system) or None,
            tools=to_gemini_tools(types_mod, tools),
            max_output_tokens=max_tokens,
        )
        raw = client.models.generate_content_stream(
            model=model,
            contents=to_gemini_contents(types_mod, messages),
            config=config,
        )
        return _GeminiStream(raw)

    def create(self, *, model: str, messages: list[dict], system: Any = None,
               tools: list[dict] | None = None, max_tokens: int = 1024, **_: Any) -> LLMResponse:
        client, types_mod = self._parent._ensure()
        config = types_mod.GenerateContentConfig(
            system_instruction=system_to_text(system) or None,
            tools=to_gemini_tools(types_mod, tools),
            max_output_tokens=max_tokens,
        )
        resp = client.models.generate_content(
            model=model,
            contents=to_gemini_contents(types_mod, messages),
            config=config,
        )
        content: list = []
        candidates = getattr(resp, "candidates", None) or []
        if candidates:
            text, calls = _parse_parts(candidates[0])
            if text:
                content.append(TextBlock(text=text))
            for i, (name, args) in enumerate(calls):
                content.append(ToolUseBlock(id=f"call_{i}", name=name, input=args))
        u = getattr(resp, "usage_metadata", None)
        usage = Usage(
            input_tokens=getattr(u, "prompt_token_count", 0) if u else 0,
            output_tokens=getattr(u, "candidates_token_count", 0) if u else 0,
        )
        return LLMResponse(content=content, usage=usage)


class GeminiClient:
    """Anthropic-shaped client backed by the google-genai SDK (imported lazily)."""

    def __init__(self, api_key: str, timeout: float = 60.0) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._client: Any = None
        self._types: Any = None
        self.messages = _GeminiMessages(self)

    def _ensure(self) -> tuple[Any, Any]:
        if self._client is None:
            try:
                from google import genai
                from google.genai import types as types_mod
            except ImportError as exc:  # pragma: no cover - env-dependent
                raise RuntimeError(
                    "Gemini provider selected but the 'google-genai' package isn't "
                    "installed. Run: pip install google-genai"
                ) from exc
            self._client = genai.Client(api_key=self._api_key)
            self._types = types_mod
        return self._client, self._types
