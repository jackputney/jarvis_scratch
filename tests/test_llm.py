"""LLM provider layer — translation, streaming round-trips, factory. No SDKs needed."""

from types import SimpleNamespace as NS

import pytest

from llm import PROVIDERS, get_llm_client
from llm.base import TextBlock, ToolUseBlock
from llm.openai_client import OpenAIClient, to_openai_messages, to_openai_tools


# --- factory ---------------------------------------------------------------

def test_get_llm_client_defaults_to_anthropic():
    import anthropic
    cfg = NS(llm_provider="anthropic", anthropic_api_key="sk-ant")
    assert isinstance(get_llm_client(cfg), anthropic.Anthropic)


def test_get_llm_client_openai_and_gemini_are_lazy():
    # These must construct without the openai/google-genai SDKs installed.
    from llm.gemini_client import GeminiClient
    assert isinstance(get_llm_client(NS(llm_provider="openai", openai_api_key="k")), OpenAIClient)
    assert isinstance(get_llm_client(NS(llm_provider="gemini", gemini_api_key="k")), GeminiClient)


def test_providers_listed():
    assert set(PROVIDERS) == {"anthropic", "openai", "gemini"}


# --- OpenAI translation ----------------------------------------------------

def test_to_openai_tools_shape():
    tools = [{"name": "get_weather", "description": "w", "input_schema": {"type": "object"}}]
    out = to_openai_tools(tools)
    assert out[0]["type"] == "function"
    assert out[0]["function"]["name"] == "get_weather"
    assert out[0]["function"]["parameters"] == {"type": "object"}


def test_to_openai_messages_round_trip():
    messages = [
        {"role": "user", "content": "weather?"},
        {"role": "assistant", "content": [
            TextBlock("let me check"),
            ToolUseBlock(id="t1", name="get_weather", input={"location": "NYC"}),
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "Sunny"},
        ]},
    ]
    out = to_openai_messages([{"type": "text", "text": "You are Jarvis"}], messages)
    assert out[0] == {"role": "system", "content": "You are Jarvis"}
    assert out[1] == {"role": "user", "content": "weather?"}
    assistant = out[2]
    assert assistant["role"] == "assistant"
    assert assistant["content"] == "let me check"
    assert assistant["tool_calls"][0]["id"] == "t1"
    assert assistant["tool_calls"][0]["function"]["name"] == "get_weather"
    tool_msg = out[3]
    assert tool_msg == {"role": "tool", "tool_call_id": "t1", "content": "Sunny"}


# --- OpenAI streaming adapter ---------------------------------------------

def _openai_chunks():
    yield NS(choices=[NS(delta=NS(content="Hello ", tool_calls=None))], usage=None)
    yield NS(choices=[NS(delta=NS(content="there", tool_calls=None))], usage=None)
    yield NS(choices=[NS(delta=NS(content=None, tool_calls=[
        NS(index=0, id="call_1", function=NS(name="get_weather", arguments='{"location":'))
    ]))], usage=None)
    yield NS(choices=[NS(delta=NS(content=None, tool_calls=[
        NS(index=0, id=None, function=NS(name=None, arguments='"NYC"}'))
    ]))], usage=None)
    yield NS(choices=[], usage=NS(prompt_tokens=12, completion_tokens=7))


def test_openai_stream_yields_text_and_assembles_response(monkeypatch):
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _openai_chunks()

    fake_client = NS(chat=NS(completions=NS(create=fake_create)))
    client = OpenAIClient(api_key="k")
    monkeypatch.setattr(client, "_ensure", lambda: fake_client)

    stream = client.messages.stream(
        model="gpt-4o-mini",
        system=[{"type": "text", "text": "sys"}],
        tools=[{"name": "get_weather", "description": "", "input_schema": {"type": "object"}}],
        messages=[{"role": "user", "content": "weather in NYC?"}],
        max_tokens=256,
    )
    with stream as s:
        deltas = list(s.text_stream)
        resp = s.get_final_message()

    assert deltas == ["Hello ", "there"]
    assert captured["stream"] is True
    assert resp.content[0].type == "text"
    assert resp.content[0].text == "Hello there"
    tool_block = resp.content[1]
    assert tool_block.type == "tool_use"
    assert tool_block.name == "get_weather"
    assert tool_block.input == {"location": "NYC"}
    assert resp.usage.input_tokens == 12
    assert resp.usage.output_tokens == 7


# --- Gemini translation + adapter (fake types module) ----------------------

def _fake_gemini_types():
    """A stand-in google.genai.types where each constructor yields a namespace."""
    return NS(
        Part=lambda **kw: NS(text=kw.get("text"), function_call=kw.get("function_call"),
                             function_response=kw.get("function_response")),
        FunctionCall=lambda **kw: NS(name=kw["name"], args=kw.get("args")),
        FunctionResponse=lambda **kw: NS(name=kw["name"], response=kw.get("response")),
        Content=lambda **kw: NS(role=kw["role"], parts=kw["parts"]),
        Tool=lambda **kw: NS(function_declarations=kw["function_declarations"]),
        FunctionDeclaration=lambda **kw: NS(**kw),
        GenerateContentConfig=lambda **kw: NS(**kw),
    )


def test_gemini_contents_map_roles_and_tool_results():
    from llm.gemini_client import to_gemini_contents
    t = _fake_gemini_types()
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [ToolUseBlock(id="t1", name="get_weather", input={"q": 1})]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "Sunny"}]},
    ]
    contents = to_gemini_contents(t, messages)
    assert contents[0].role == "user"
    assert contents[1].role == "model"  # assistant → model
    # tool_result resolved to the function name (t1 → get_weather)
    fr = contents[2].parts[0].function_response
    assert fr.name == "get_weather"
    assert fr.response == {"result": "Sunny"}


def test_gemini_stream_assembles_response(monkeypatch):
    from llm.gemini_client import GeminiClient

    def _chunks():
        yield NS(candidates=[NS(content=NS(parts=[NS(text="Hi", function_call=None)]))],
                 usage_metadata=None)
        yield NS(candidates=[NS(content=NS(parts=[
            NS(text=None, function_call=NS(name="get_weather", args={"location": "NYC"}))
        ]))], usage_metadata=NS(prompt_token_count=9, candidates_token_count=4))

    fake_client = NS(models=NS(generate_content_stream=lambda **kw: _chunks()))
    client = GeminiClient(api_key="k")
    monkeypatch.setattr(client, "_ensure", lambda: (fake_client, _fake_gemini_types()))

    stream = client.messages.stream(
        model="gemini-1.5-flash",
        system="sys",
        tools=[{"name": "get_weather", "description": "", "input_schema": {"type": "object"}}],
        messages=[{"role": "user", "content": "weather?"}],
    )
    with stream as s:
        deltas = list(s.text_stream)
        resp = s.get_final_message()

    assert deltas == ["Hi"]
    assert resp.content[0].text == "Hi"
    assert resp.content[1].name == "get_weather"
    assert resp.content[1].input == {"location": "NYC"}
    assert resp.usage.input_tokens == 9
    assert resp.usage.output_tokens == 4
