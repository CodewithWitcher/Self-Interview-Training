"""Settings from the environment, optionally through .env (SG 5, AR 8)."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

PROVIDERS = ("ollama", "anthropic")
EFFORTS = ("low", "medium", "high", "xhigh", "max")


class SettingsError(ValueError):
    """A setting has a value the app cannot use. The message names the variable."""


@dataclass(frozen=True)
class Settings:
    repo_root: Path = REPO_ROOT
    port: int = 8000
    data_dir: Path = REPO_ROOT / "data"
    default_provider: str = "ollama"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:8b"
    ollama_num_ctx: int = 8192
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: str = "medium"
    anthropic_api_key: str | None = field(default=None, repr=False)
    llm_timeout_s: float = 180.0
    dev_fake: bool = False
    whisper_model: str = "base.en"
    whisper_device: str = "cpu"
    whisper_compute: str = "int8"
    whisper_prompt: str = ""

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise SettingsError(f"{name} must be a whole number, got {raw!r}") from None


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise SettingsError(f"{name} must be a number, got {raw!r}") from None
    if value <= 0:
        raise SettingsError(f"{name} must be above 0, got {raw!r}")
    return value


def _str(name: str, default: str) -> str:
    raw = os.environ.get(name, "").strip()
    return raw or default


def _choice(name: str, default: str, allowed: tuple[str, ...]) -> str:
    value = _str(name, default)
    if value not in allowed:
        raise SettingsError(f"{name} must be one of {', '.join(allowed)}, got {value!r}")
    return value


def load_settings(repo_root: Path = REPO_ROOT) -> Settings:
    """Load .env from the repository root, then read the environment. The environment wins."""
    load_dotenv(repo_root / ".env", override=False, encoding="utf-8")
    data_dir = Path(_str("SIT_DATA_DIR", "data"))
    if not data_dir.is_absolute():
        data_dir = repo_root / data_dir
    port = _int("SIT_PORT", 8000)
    if not 1 <= port <= 65535:
        raise SettingsError(f"SIT_PORT must be between 1 and 65535, got {port}")
    return Settings(
        repo_root=repo_root,
        port=port,
        data_dir=data_dir,
        default_provider=_choice("SIT_DEFAULT_PROVIDER", "ollama", PROVIDERS),
        ollama_url=_str("SIT_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
        ollama_model=_str("SIT_OLLAMA_MODEL", "llama3.1:8b"),
        ollama_num_ctx=_int("SIT_OLLAMA_NUM_CTX", 8192),
        anthropic_model=_str("SIT_ANTHROPIC_MODEL", "claude-opus-5-5"),
        anthropic_effort=_choice("SIT_ANTHROPIC_EFFORT", "medium", EFFORTS),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        llm_timeout_s=_float("SIT_LLM_TIMEOUT_S", 180.0),
        dev_fake=_choice("SIT_DEV_FAKE", "0", ("0", "1")) == "1",
        whisper_model=_str("SIT_WHISPER_MODEL", "base.en"),
        whisper_device=_str("SIT_WHISPER_DEVICE", "cpu"),
        whisper_compute=_str("SIT_WHISPER_COMPUTE", "int8"),
        whisper_prompt=os.environ.get("SIT_WHISPER_PROMPT", "").strip(),
    )
