"""Config hot-reload smoke tests — dashboard edits land in config.json and reload."""

from config import Config


def test_update_persisted_round_trips(temp_env):
    cfg = Config.update_persisted({
        "daily_budget_usd": 9.0,
        "confirm_before_execute": False,
        "routing_word_threshold": 33,
    })
    assert cfg.daily_budget_usd == 9.0
    assert cfg.confirm_before_execute is False
    assert cfg.routing_word_threshold == 33

    # A fresh load (what the pipeline does each cycle) sees the new values.
    reloaded = Config.load()
    assert reloaded.daily_budget_usd == 9.0
    assert reloaded.confirm_before_execute is False
    assert reloaded.routing_word_threshold == 33


def test_type_coercion_from_strings(temp_env):
    cfg = Config.update_persisted({
        "daily_budget_usd": "5.5",      # str → float
        "routing_word_threshold": "15",  # str → int
        "wake_word_enabled": "false",    # str → bool
    })
    assert cfg.daily_budget_usd == 5.5
    assert cfg.routing_word_threshold == 15
    assert cfg.wake_word_enabled is False


def test_unknown_and_secret_keys_ignored(temp_env):
    cfg = Config.update_persisted({
        "anthropic_api_key": "leaked",  # env-only, must never persist
        "nonsense": 123,
    })
    persisted = cfg.to_persisted_dict()
    assert "anthropic_api_key" not in persisted
    assert "nonsense" not in persisted
