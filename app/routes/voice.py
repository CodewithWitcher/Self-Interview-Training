"""Audio upload: transcribe a recording and return JSON (F14, F16)."""

from typing import Annotated

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse

from app import sessions, voice
from app.db import Conn
from app.routes.sessions import load_all

router = APIRouter()


def error(message: str, status_code: int = 422) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


@router.post("/profiles/{pid}/sessions/{sid}/attempts/{aid}/audio")
async def audio(
    request: Request,
    conn: Conn,
    pid: int,
    sid: int,
    aid: int,
    audio: Annotated[UploadFile | None, File()] = None,
):
    _, session, attempt = load_all(conn, pid, sid, aid)
    turn = sessions.current_turn(conn, aid)
    if (
        session["status"] != "active"
        or attempt["status"] == "done"
        or turn["answer_text"] is not None
    ):
        return error("This question is not waiting for an answer.", 409)
    if audio is None:
        return error("No recording was received.")
    data = await audio.read(voice.MAX_AUDIO_BYTES + 1)
    try:
        transcript = voice.transcribe(data, request.app.state.settings)
    except voice.VoiceError as exc:
        return error(str(exc))
    except voice.SpeechModelMissing as exc:
        return error(str(exc), 503)
    finally:
        del data  # The audio is discarded once transcribed.
    m = voice.delivery_metrics(transcript.segments, transcript.text)
    with conn:
        conn.execute(
            "UPDATE turns SET input_mode = 'voice', speech_ms = ?, first_word_delay_ms = ?, "
            "wpm = ?, filler_count = ? WHERE id = ? AND answer_text IS NULL",
            (m.speech_ms, m.first_word_delay_ms, m.wpm, m.filler_count, turn["id"]),
        )
    return JSONResponse({"text": transcript.text})
