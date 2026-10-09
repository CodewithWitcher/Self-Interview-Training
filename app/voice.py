"""Transcription and delivery metrics (F14, F16, PS 9)."""

import io
import math
import re
import threading
from dataclasses import dataclass
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


MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_AUDIO_SECONDS = 300
SEGMENT_END_SLACK_S = 0.5
MIN_WPM_SPEECH_MS = 5000

FILLER = re.compile(
    r"\b(um+|uh+|er+m?|hmm+|you know|i mean|sort of|kind of|basically|like)\b",
    re.IGNORECASE,
)
_HAS_WORD = re.compile(r"[A-Za-z0-9]")


class VoiceError(ValueError):
    """A recording that cannot be used. The message is shown to the user."""


@dataclass(frozen=True)
class Transcript:
    text: str
    segments: list  # objects with start, end and text, after the guards


def transcribe(data: bytes, settings: Settings) -> Transcript:
    """Transcribe audio bytes in memory. Nothing is written to disk (AR 9 rule 13)."""
    import av

    if len(data) > MAX_AUDIO_BYTES:
        raise VoiceError("The recording is larger than 25 MB.")
    model = load_model(settings)
    try:
        segments, info = model.transcribe(
            io.BytesIO(data),
            language="en",
            vad_filter=True,
            initial_prompt=settings.whisper_prompt or None,
        )
        if info.duration > MAX_AUDIO_SECONDS:
            raise VoiceError("The recording is longer than 5 minutes.")
        kept = [
            s
            for s in segments
            if s.end <= info.duration + SEGMENT_END_SLACK_S and _HAS_WORD.search(s.text)
        ]
    except av.error.FFmpegError:
        raise VoiceError(
            "This recording could not be read. Try again, or type your answer."
        ) from None
    if not kept:
        raise VoiceError("No speech was detected. Check the microphone, or type your answer.")
    text = " ".join(s.text.strip() for s in kept).strip()
    return Transcript(text, kept)


@dataclass(frozen=True)
class Metrics:
    speech_ms: int
    first_word_delay_ms: int
    wpm: int | None
    filler_count: int


def delivery_metrics(segments: list, text: str) -> Metrics:
    """Pace, first word delay and filler count of PS 9.2. Approximate, never part of a score."""
    first, last = segments[0], segments[-1]
    speech_ms = int((last.end - first.start) * 1000 + 0.5)
    words = len(text.split())
    wpm = None
    if speech_ms >= MIN_WPM_SPEECH_MS:
        wpm = math.floor(words / (speech_ms / 60000) + 0.5)
    return Metrics(
        speech_ms=speech_ms,
        first_word_delay_ms=int(first.start * 1000 + 0.5),
        wpm=wpm,
        filler_count=len(FILLER.findall(text)),
    )
