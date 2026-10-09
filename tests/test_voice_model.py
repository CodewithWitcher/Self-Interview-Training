from dataclasses import replace

import pytest

from app import voice
from app.config import REPO_ROOT


def test_missing_speech_model_names_fetch_command(settings):
    with pytest.raises(voice.SpeechModelMissing, match="--voice"):
        voice.load_model(replace(settings, dev_fake=False))


@pytest.mark.models
def test_speech_model_loads_offline(settings, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    real = replace(settings, dev_fake=False, data_dir=REPO_ROOT / "data")
    assert voice.model_present(real), "Run uv run python -m app.fetch_models --voice first"
    assert voice.load_model(real) is not None
