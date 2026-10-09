from dataclasses import replace
from types import SimpleNamespace

import av
import pytest

from app import voice
from app.config import REPO_ROOT
from tests.helpers import FIXTURES, current, ready_profile, start_session

SENTENCE = (
    "Um, I think a tuple is immutable, so, uh, you can use it as a dictionary key. "
    "A list is mutable, like, you can append to it."
)


def seg(start, end, text):
    return SimpleNamespace(start=start, end=end, text=text)


class StubModel:
    def __init__(self, segments=(), duration=10.0, raises=None):
        self.segments, self.duration, self.raises = list(segments), duration, raises
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise self.raises
        return iter(self.segments), SimpleNamespace(duration=self.duration)


@pytest.fixture
def stub(monkeypatch):
    def install(model):
        monkeypatch.setattr(voice, "load_model", lambda settings: model)
        return model

    return install


def test_guards_drop_late_and_punctuation_segments(settings, stub):
    stub(
        StubModel(
            [seg(1.0, 4.0, " Hello there."), seg(4.0, 9.9, " ..."), seg(10.0, 10.6, " Thanks.")],
            10.0,
        )
    )
    t = voice.transcribe(b"x", settings)
    assert t.text == "Hello there."
    assert len(t.segments) == 1


def test_segment_inside_slack_is_kept(settings, stub):
    stub(StubModel([seg(1.0, 10.4, " Kept.")], 10.0))
    assert voice.transcribe(b"x", settings).text == "Kept."


def test_transcribe_options(settings, stub):
    model = stub(StubModel([seg(0, 1, "a")]))
    voice.transcribe(b"x", replace(settings, whisper_prompt="Um, uh, like."))
    assert model.calls[0] == {
        "language": "en",
        "vad_filter": True,
        "initial_prompt": "Um, uh, like.",
    }
    voice.transcribe(b"x", settings)
    assert model.calls[1]["initial_prompt"] is None


def test_no_segment_is_no_speech(settings, stub):
    stub(StubModel([seg(0.5, 1.0, " ?! ")]))
    with pytest.raises(voice.VoiceError, match="No speech was detected"):
        voice.transcribe(b"x", settings)


def test_decoding_error_is_unreadable(settings, stub):
    stub(StubModel(raises=av.error.InvalidDataError(1094995529, "Invalid data")))
    with pytest.raises(voice.VoiceError, match="could not be read"):
        voice.transcribe(b"x", settings)


def test_long_recording_is_rejected(settings, stub):
    stub(StubModel([seg(0, 1, "a")], duration=301))
    with pytest.raises(voice.VoiceError, match="5 minutes"):
        voice.transcribe(b"x", settings)


def test_measured_example():
    segments = [seg(1.23, 6.0, SENTENCE.split(" key.")[0] + " key."), seg(6.2, 12.23, "rest")]
    m = voice.delivery_metrics(segments, SENTENCE)
    assert len(SENTENCE.split()) == 27
    assert (m.speech_ms, m.wpm, m.filler_count, m.first_word_delay_ms) == (11000, 147, 3, 1230)


def test_short_speech_has_no_pace():
    m = voice.delivery_metrics([seg(0.5, 4.0, "hi")], "hi there")
    assert m.wpm is None and m.speech_ms == 3500


def session_turn(client, conn):
    pid = ready_profile(client)
    sid = start_session(client, conn, pid)
    aid, turn = current(conn, sid)
    return f"/profiles/{pid}/sessions/{sid}/attempts/{aid}/audio", turn


def test_route_returns_text_and_stores_metrics(client, conn, stub):
    stub(StubModel([seg(1.23, 6.0, " Um, I think"), seg(6.2, 12.23, " it works.")], 13.0))
    url, turn = session_turn(client, conn)
    r = client.post(url, files={"audio": ("a.webm", b"bytes", "audio/webm")})
    assert r.status_code == 200
    assert r.json() == {"text": "Um, I think it works."}
    row = conn.execute("SELECT * FROM turns WHERE id = ?", (turn["id"],)).fetchone()
    assert (
        row["input_mode"],
        row["speech_ms"],
        row["first_word_delay_ms"],
        row["filler_count"],
    ) == (
        "voice",
        11000,
        1230,
        1,
    )
    assert row["wpm"] == 27 and row["answer_text"] is None


def test_route_error_is_json(client, conn, stub):
    stub(StubModel([]))
    url, _ = session_turn(client, conn)
    r = client.post(url, files={"audio": ("a.webm", b"bytes", "audio/webm")})
    assert r.status_code == 422
    assert "No speech was detected" in r.json()["error"]


def test_26_mb_body_is_rejected(client, conn, stub):
    stub(StubModel([seg(0, 1, "a")]))
    url, _ = session_turn(client, conn)
    r = client.post(url, files={"audio": ("a.webm", b"0" * (26 * 1024 * 1024), "audio/webm")})
    assert r.status_code == 422
    assert "25 MB" in r.json()["error"]


def test_no_file_written_under_data_folder(client, conn, stub, settings):
    stub(StubModel([seg(0, 1, "a")]))
    url, _ = session_turn(client, conn)
    before = sorted(settings.data_dir.rglob("*"))
    client.post(url, files={"audio": ("a.webm", b"0" * (3 * 1024 * 1024), "audio/webm")})
    assert sorted(settings.data_dir.rglob("*")) == before


def test_missing_speech_model_is_reported(client, conn):
    url, _ = session_turn(client, conn)
    r = client.post(url, files={"audio": ("a.webm", b"x", "audio/webm")})
    assert r.status_code == 503 and "--voice" in r.json()["error"]


@pytest.fixture
def real(settings):
    s = replace(settings, dev_fake=False, data_dir=REPO_ROOT / "data")
    assert voice.model_present(s), "Run uv run python -m app.fetch_models --voice first"
    return s


@pytest.mark.models
def test_fixture_transcript(real):
    t = voice.transcribe((FIXTURES / "speech_sample.webm").read_bytes(), real)
    lowered = t.text.lower()
    assert "tuple is immutable" in lowered
    assert "dictionary key" in lowered
    m = voice.delivery_metrics(t.segments, t.text)
    assert 800 <= m.first_word_delay_ms <= 1800


@pytest.mark.models
def test_silence_gives_no_speech(real):
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 32000)
    with pytest.raises(voice.VoiceError, match="No speech"):
        voice.transcribe(buf.getvalue(), real)
