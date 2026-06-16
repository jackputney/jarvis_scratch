"""
llm/base.py — Provider-neutral response shapes + Anthropic-format translation.

The whole pipeline speaks Anthropic's request/response shape (system blocks,
tool_use / tool_result content blocks, `response.content`, `response.usage`).
Rather than rewrite that, non-Anthropic adapters translate Anthropic-shaped
input to their native API and return these duck-typed objects, which expose the
exact attributes pipeline reads: block.type / .text / .id / .name / .input and
usage.input_tokens / .output_tokens.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict
    type: str = "tool_use"


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMResponse:
    """Anthropic-shaped response: `.content` is a list of blocks, plus `.usage`."""
    content: list = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


# ---------------------------------------------------------------------------
# Helpers for reading Anthropic-format request pieces (used by every adapter).
# ---------------------------------------------------------------------------

def system_to_text(system: Any) -> str:
    """Flatten Anthropic system blocks (or a plain string) into one string."""
    if not system:
        return ""
    if isinstance(system, str):
        return system
    parts = []
    for block in system:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif isinstance(block, str):
            parts.append(block)
    return "\n\n".join(p for p in parts if p)


def _block_attr(block: Any, key: str) -> Any:
    """Read a field from a block that may be a dict or a dataclass object."""
    if isinstance(block, dict):
        return block.get(key)
    return getattr(block, key, None)


def iter_blocks(content: Any) -> list[tuple[str, Any]]:
    """Yield (type, block) for each block in a message's content.

    `content` may be a plain string (→ one text block), a list of dataclass
    blocks (assistant turns we produced) or a list of dicts (tool_result /
    text turns the pipeline built).
    """
    if isinstance(content, str):
        return [("text", {"type": "text", "text": content})]
    out = []
    for block in content or []:
        out.append((_block_attr(block, "type"), block))
    return out


def tool_input_json(block: Any) -> str:
    """Serialise a tool_use block's input dict to a JSON string."""
    return json.dumps(_block_attr(block, "input") or {})
