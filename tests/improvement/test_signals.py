"""Signal heuristic tests."""

from improvement.signals import detect_correction, detect_repeat_request


def test_detect_correction_asr_high_overlap():
    assert detect_correction("send email to Jeff", "send email to Jeff please") == "asr_correction"


def test_detect_correction_command_negation():
    assert detect_correction("schedule meeting tomorrow", "no I said next week") == "command_correction"


def test_detect_correction_none_different_topic():
    assert detect_correction("what is the weather", "play some music") is None


def test_detect_repeat_request_within_window():
    history = ["turn on the lights", "set a timer for five minutes"]
    assert detect_repeat_request(history, "turn on the lights now") is True


def test_detect_repeat_request_no_repeat():
    history = ["turn on the lights", "set a timer"]
    assert detect_repeat_request(history, "what is the capital of France") is False


def test_detect_correction_empty_inputs():
    assert detect_correction(None, None) is None
    assert detect_correction("hello", "") is None


def test_detect_repeat_request_single_word():
    assert detect_repeat_request(["hi"], "hi") is False
