"""STT backend configuration."""

from config import Config


def test_stt_backend_config_option(temp_env):
    cfg = Config.update_persisted({"stt_backend": "faster", "stt_model": "small"})
    assert cfg.stt_backend == "faster"
    assert cfg.stt_model == "small"
    reloaded = Config.load()
    assert reloaded.stt_backend == "faster"
