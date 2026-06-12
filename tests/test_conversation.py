"""In-memory conversation history caps."""

import conversation


def setup_function() -> None:
    conversation.clear_history()


def test_build_messages_empty():
    assert conversation.build_messages(8, 6000) == []


def test_build_messages_includes_recent_turns():
    conversation.add_turn("hello", "hi there")
    conversation.add_turn("what time?", "five pm")
    msgs = conversation.build_messages(8, 6000)
    assert msgs == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
        {"role": "user", "content": "what time?"},
        {"role": "assistant", "content": "five pm"},
    ]


def test_build_messages_respects_turn_cap():
    for i in range(10):
        conversation.add_turn(f"u{i}", f"a{i}")
    msgs = conversation.build_messages(3, 6000)
    assert len(msgs) == 6
    assert msgs[0]["content"] == "u7"
    assert msgs[-1]["content"] == "a9"


def test_build_messages_respects_char_budget():
    conversation.add_turn("a" * 2000, "b" * 2000)
    conversation.add_turn("short", "reply")
    msgs = conversation.build_messages(8, 2500)
    assert len(msgs) == 2
    assert msgs[0]["content"] == "short"
