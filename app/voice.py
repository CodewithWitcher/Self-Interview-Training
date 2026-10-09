"""Transcription and delivery metrics (F14, F16, PS 9)."""

import threading
from pathlib import Path

from app.config import Settings

WHISPER_FILES = ("model.bin", "config.json")

_lock = threading.Lock()
_models: dict[str, object] = {}


class SpeechModelMissing(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "The speech model is not downloaded. Run: uv run python -m app.fetch_models --voice"
        )


def model_dir(settings: Settings) -> Path:
    return settings.models_dir / "whisper"


def model_present(settings: Settings) -> bool:
    return any(model_dir(settings).rglob("model.bin"))


def load_model(settings: Settings, local_files_only: bool = True):
    """Load the speech model once, behind a lock."""
    key = f"{model_dir(settings)}|{settings.whisper_model}|{settings.whisper_compute}"
    with _lock:
        model = _models.get(key)
        if model is None:
            from faster_whisper import WhisperModel

            if local_files_only and not model_present(settings):
                raise SpeechModelMissing()
            try:
                model = WhisperModel(
                    settings.whisper_model,
                    device=settings.whisper_device,
                    compute_type=settings.whisper_compute,
                    download_root=str(model_dir(settings)),
                    local_files_only=local_files_only,
                )
            except (OSError, ValueError, RuntimeError) as exc:
                if local_files_only:
                    raise SpeechModelMissing() from exc
                raise
            _models[key] = model
    return model
