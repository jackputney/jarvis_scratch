"""STT backend configuration."""

from config import Config


def test_stt_backend_config_option(temp_env):
    cfg = Config.update_persisted({"stt_backend": "faster", "stt_model": "small"})
    assert cfg.stt_backend == "faster"
    assert cfg.stt_model == "small"
    reloaded = Config.load()
    assert reloaded.stt_backend == "faster"


def test_stt_model_defaults_large_v3_turbo():
    cfg = Config()
    assert cfg.stt_model == "large-v3-turbo"
    assert cfg.whisper_model == "large-v3-turbo"
    assert cfg.effective_stt_model() == "large-v3-turbo"


def test_stt_device_compute_persisted(temp_env):
    cfg = Config.update_persisted({"stt_device": "cpu", "stt_compute_type": "int8"})
    assert cfg.stt_device == "cpu"
    assert cfg.stt_compute_type == "int8"
    reloaded = Config.load()
    assert reloaded.stt_device == "cpu"
    assert reloaded.stt_compute_type == "int8"
