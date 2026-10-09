from pathlib import Path

import pytest

from app.config import Settings, SettingsError, load_settings

VARIABLES = [
    "SIT_PORT",
    "SIT_DATA_DIR",
    "SIT_DEFAULT_PROVIDER",
    "SIT_OLLAMA_URL",
    "SIT_OLLAMA_MODEL",
    "SIT_OLLAMA_NUM_CTX",
    "SIT_ANTHROPIC_MODEL",
    "SIT_ANTHROPIC_EFFORT",
    "ANTHROPIC_API_KEY",
    "SIT_LLM_TIMEOUT_S",
    "SIT_DEV_FAKE",
    "SIT_WHISPER_MODEL",
    "SIT_WHISPER_DEVICE",
    "SIT_WHISPER_COMPUTE",
    "SIT_WHISPER_PROMPT",
]


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_defaults_match_setup_guide(clean_env):
    s = load_settings(clean_env)
    assert s.port == 8000
    assert s.data_dir == clean_env / "data"
    assert s.default_provider == "ollama"
    assert s.ollama_url == "http://127.0.0.1:11434"
    assert s.ollama_model == "llama3.1:8b"
    assert s.ollama_num_ctx == 8192
    assert s.anthropic_model == "claude-opus-5-5"
    assert s.anthropic_effort == "medium"
    assert s.anthropic_api_key is None
    assert s.llm_timeout_s == 180
    assert s.dev_fake is False
    assert s.whisper_model == "base.en"
    assert s.whisper_device == "cpu"
    assert s.whisper_compute == "int8"
    assert s.whisper_prompt == ""


def test_dataclass_defaults_match_loader(clean_env):
    loaded = load_settings(clean_env)
    built = Settings(repo_root=clean_env, data_dir=clean_env / "data")
    assert built == loaded


def test_environment_beats_dotenv(clean_env, monkeypatch):
    (clean_env / ".env").write_text("SIT_PORT=9001\nSIT_OLLAMA_MODEL=from-file\n", encoding="utf-8")
    monkeypatch.setenv("SIT_PORT", "9002")
    s = load_settings(clean_env)
    assert s.port == 9002
    assert s.ollama_model == "from-file"


def test_data_dir_with_spaces_resolves(clean_env, monkeypatch):
    root = clean_env / "Self Interview Training"
    root.mkdir()
    monkeypatch.setenv("SIT_DATA_DIR", "my data")
    s = load_settings(root)
    assert s.data_dir == root / "my data"
    assert s.db_path == root / "my data" / "app.db"


def test_absolute_data_dir_is_kept(clean_env, monkeypatch):
    target = clean_env / "elsewhere"
    monkeypatch.setenv("SIT_DATA_DIR", str(target))
    assert load_settings(clean_env / "repo").data_dir == target


def test_unknown_provider_raises(clean_env, monkeypatch):
    monkeypatch.setenv("SIT_DEFAULT_PROVIDER", "other")
    with pytest.raises(SettingsError, match="SIT_DEFAULT_PROVIDER"):
        load_settings(clean_env)


@pytest.mark.parametrize("name", ["SIT_PORT", "SIT_OLLAMA_NUM_CTX", "SIT_LLM_TIMEOUT_S"])
def test_non_numeric_number_raises(clean_env, monkeypatch, name):
    monkeypatch.setenv(name, "abc")
    with pytest.raises(SettingsError, match=name):
        load_settings(clean_env)


def test_key_is_not_in_repr(clean_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    s = load_settings(clean_env)
    assert s.anthropic_api_key == "sk-secret"
    assert "sk-secret" not in repr(s)


def test_repo_root_is_path():
    assert isinstance(Settings().repo_root, Path)
