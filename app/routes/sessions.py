"""Practice sessions: start, question page, answer, scoring, follow-ups, end (F4 to F9)."""

import json
import sqlite3

from fastapi import APIRouter, Form, HTTPException, Request

from app import evaluation, llm, sessions
from app.db import Conn
from app.routes import load_profile, model_picker, parse_model, redirect, render

router = APIRouter()


def flash(request: Request, session_id: int, messages: list[str]) -> None:
    # ponytail: start notices live in memory until the first page view, so a restart in between
    # drops them. Store them on the session row if that ever matters.
    if messages:
        request.app.state.flash[session_id] = messages


def take_flash(request: Request, session_id: int) -> list[str]:
    return request.app.state.flash.pop(session_id, [])


def start_form_context(conn, profile, settings, **extra) -> dict:
    context = {
        "topics": sessions.active_topics(conn, profile["id"]),
        "form_topics": None,
        "form_count": 5,
        "form_difficulty": "medium",
        "start_error": None,
    }
    context.update(model_picker(conn, profile["id"], settings))
    context.update(extra)
    return context


def load_session(conn: sqlite3.Connection, pid: int, sid: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM sessions WHERE id = ? AND profile_id = ?", (sid, pid)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404)
    return row


def load_attempt(conn: sqlite3.Connection, sid: int, aid: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM attempts WHERE id = ? AND session_id = ?", (aid, sid)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404)
    return row


@router.post("/profiles/{pid}/sessions")
async def start(request: Request, conn: Conn, pid: int):
    from app.routes.profiles import profile_page

    profile = load_profile(conn, pid)
    settings = request.app.state.settings
    active = sessions.active_session(conn, pid)
    if active:
        return redirect(f"/profiles/{pid}/sessions/{active['id']}")
    form = await request.form()
    topic_ids = [int(v) for v in form.getlist("topics") if str(v).isdigit()]
    count = str(form.get("count", ""))
    difficulty = str(form.get("difficulty", ""))
    review_only = form.get("review_only") == "1"
    choice = parse_model(str(form.get("model", "")), settings)

    def fail(message: str):
        return profile_page(
            request,
            conn,
            profile,
            422,
            form_topics=topic_ids,
            form_count=int(count) if count.isdigit() else 5,
            form_difficulty=difficulty,
            form_review_only=review_only,
            start_error=message,
        )

    if not count.isdigit() or int(count) not in sessions.COUNTS:
        return fail("Choose 3, 5 or 10 questions.")
    if difficulty not in sessions.DIFFICULTIES:
        return fail("Choose a difficulty.")
    if choice is None:
        return fail("Choose a model from the list.")
    active_ids = {t["id"] for t in sessions.active_topics(conn, pid)}
    topic_ids = [t for t in topic_ids if t in active_ids]
    if not topic_ids and not review_only:
        return fail("Choose at least one topic.")
    provider, model = choice
    comp = sessions.compose(
        conn,
        pid,
        topic_ids,
        int(count),
        difficulty,
        provider,
        model,
        request.app.state.rng,
        settings,
        request.app.state.today(),
        review_only=review_only,
    )
    failures = [f"No questions for {name}: {reason}" for name, reason in comp.failed]
    if not comp.items:
        if review_only:
            return fail("Nothing is due for review.")
        return fail("No question could be found or written. " + " ".join(failures))
    sid = sessions.start(conn, pid, comp.items, provider, model, difficulty)
    messages = failures[:]
    if len(comp.items) < comp.wanted:
        messages.append(
            f"Found {len(comp.items)} of {comp.wanted} questions, so this session is shorter."
        )
    flash(request, sid, messages)
    return redirect(f"/profiles/{pid}/sessions/{sid}")


@router.get("/profiles/{pid}/sessions/{sid}")
def open_session(request: Request, conn: Conn, pid: int, sid: int):
    load_profile(conn, pid)
    session = load_session(conn, pid, sid)
    attempt = sessions.current_attempt(conn, sid)
    if session["status"] == "completed" or attempt is None:
        return redirect(f"/profiles/{pid}/sessions/{sid}/summary")
    return redirect(f"/profiles/{pid}/sessions/{sid}/attempts/{attempt['id']}")


@router.get("/profiles/{pid}/sessions/{sid}/attempts/{aid}")
def attempt_page(request: Request, conn: Conn, pid: int, sid: int, aid: int):
    profile = load_profile(conn, pid)
    session = load_session(conn, pid, sid)
    attempt = load_attempt(conn, sid, aid)
    return render_attempt(request, conn, profile, session, attempt)


def render_attempt(request, conn, profile, session, attempt, status_code=200, **extra):
    question = conn.execute(
        "SELECT q.*, t.name AS topic_name, t.kind AS topic_kind FROM questions q "
        "JOIN topics t ON t.id = q.topic_id WHERE q.id = ?",
        (attempt["question_id"],),
    ).fetchone()
    turns = []
    for row in conn.execute(
        "SELECT * FROM turns WHERE attempt_id = ? ORDER BY level", (attempt["id"],)
    ):
        turn = dict(row)
        turn["evaluation"] = json.loads(row["eval_json"]) if row["eval_json"] else None
        turns.append(turn)
    latest = turns[-1]
    if attempt["status"] == "done":
        state = "done"
    elif latest["answer_text"] is None:
        state = "answer"
    else:
        state = "retry"
    total = conn.execute(
        "SELECT count(*) FROM attempts WHERE session_id = ?", (session["id"],)
    ).fetchone()[0]
    error_code = request.query_params.get("error", "")
    context = {
        "profile": profile,
        "session": session,
        "attempt": attempt,
        "question": question,
        "key_points": json.loads(question["key_points"]),
        "turns": turns,
        "latest": latest,
        "state": state,
        "total": total,
        "is_last": attempt["ord"] == total,
        "messages": take_flash(request, session["id"]),
        "error_title": ERROR_TITLES.get(error_code) if state == "retry" else None,
        "error_detail": request.app.state.flash.pop(("error", attempt["id"]), None),
        "answer_error": None,
        "draft": "",
        "answer_max": ANSWER_MAX,
    }
    context.update(model_picker(conn, profile["id"], request.app.state.settings))
    context["model_selected"] = f"{session['provider']}:{session['model']}"
    context.update(extra)
    return render(request, "attempt.html", status_code, **context)


ANSWER_MAX = 5000
ERROR_CODES = {
    llm.LLMUnavailable: "unavailable",
    llm.LLMOutputError: "output",
    llm.LLMRefused: "refused",
}
ERROR_TITLES = {
    "unavailable": llm.LLMUnavailable.title,
    "output": llm.LLMOutputError.title,
    "refused": llm.LLMRefused.title,
}


def attempt_url(pid: int, sid: int, aid: int) -> str:
    return f"/profiles/{pid}/sessions/{sid}/attempts/{aid}"


def score_turn(request: Request, conn, pid: int, sid: int, aid: int, turn_id: int):
    """Steps 4 to 7 of AR 6.1."""
    settings = request.app.state.settings
    try:
        result = evaluation.evaluate_turn(conn, turn_id, settings)
    except llm.LLMError as exc:
        code = next((c for cls, c in ERROR_CODES.items() if isinstance(exc, cls)), "unavailable")
        request.app.state.flash[("error", aid)] = str(exc)
        return redirect(f"{attempt_url(pid, sid, aid)}?error={code}")
    turn = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
    sessions.record_evaluation(conn, turn, result, request.app.state.today())
    return redirect(attempt_url(pid, sid, aid))


def load_all(conn, pid, sid, aid):
    profile = load_profile(conn, pid)
    session = load_session(conn, pid, sid)
    attempt = load_attempt(conn, sid, aid)
    return profile, session, attempt


@router.post("/profiles/{pid}/sessions/{sid}/attempts/{aid}/answer")
def answer(
    request: Request,
    conn: Conn,
    pid: int,
    sid: int,
    aid: int,
    text: str = Form(""),
    turn_id: str = Form(""),
):
    profile, session, attempt = load_all(conn, pid, sid, aid)
    turn = sessions.current_turn(conn, aid)
    if attempt["status"] == "done" or turn["answer_text"] is not None or str(turn["id"]) != turn_id:
        return redirect(attempt_url(pid, sid, aid))  # A double submit, or a stale form.
    clean = text.strip()
    if not 1 <= len(clean) <= ANSWER_MAX:
        message = (
            "Write an answer before submitting, or press Skip."
            if not clean
            else f"The answer has {len(clean):,} characters. The limit is {ANSWER_MAX:,}."
        )
        return render_attempt(
            request, conn, profile, session, attempt, 422, answer_error=message, draft=text
        )
    sessions.save_answer(conn, turn["id"], aid, clean)
    return score_turn(request, conn, pid, sid, aid, turn["id"])


@router.post("/profiles/{pid}/sessions/{sid}/attempts/{aid}/evaluate")
def retry(request: Request, conn: Conn, pid: int, sid: int, aid: int):
    load_all(conn, pid, sid, aid)
    turn = sessions.current_turn(conn, aid)
    if turn["answer_text"] is None or turn["score"] is not None:
        return redirect(attempt_url(pid, sid, aid))
    return score_turn(request, conn, pid, sid, aid, turn["id"])


@router.post("/profiles/{pid}/sessions/{sid}/attempts/{aid}/skip")
def skip(request: Request, conn: Conn, pid: int, sid: int, aid: int, turn_id: str = Form("")):
    _, _, attempt = load_all(conn, pid, sid, aid)
    turn = sessions.current_turn(conn, aid)
    if attempt["status"] != "done" and turn["answer_text"] is None and str(turn["id"]) == turn_id:
        sessions.skip_turn(conn, turn, request.app.state.today())
    return redirect(attempt_url(pid, sid, aid))


@router.post("/profiles/{pid}/sessions/{sid}/model")
def change_model(
    request: Request, conn: Conn, pid: int, sid: int, model: str = Form(""), back: str = Form("")
):
    load_profile(conn, pid)
    session = load_session(conn, pid, sid)
    choice = parse_model(model, request.app.state.settings)
    if choice is None:
        raise HTTPException(status_code=422, detail="Choose a model from the list.")
    if session["status"] == "active":
        sessions.change_model(conn, sid, *choice)
    target = f"/profiles/{pid}/sessions/{sid}"
    if back.isdigit():
        attempt = conn.execute(
            "SELECT id FROM attempts WHERE id = ? AND session_id = ?", (int(back), sid)
        ).fetchone()
        if attempt:
            target = attempt_url(pid, sid, attempt["id"])
    return redirect(f"{target}?notice=model_changed")


@router.post("/profiles/{pid}/sessions/{sid}/end")
def end(request: Request, conn: Conn, pid: int, sid: int):
    load_profile(conn, pid)
    session = load_session(conn, pid, sid)
    if session["status"] == "completed":
        return redirect(f"/profiles/{pid}/sessions/{sid}/summary")
    if sessions.end(conn, sid, request.app.state.today()):
        return redirect(f"/profiles/{pid}/sessions/{sid}/summary")
    return redirect(f"/profiles/{pid}?notice=session_ended")


@router.get("/profiles/{pid}/sessions/{sid}/summary")
def summary(request: Request, conn: Conn, pid: int, sid: int):
    profile = load_profile(conn, pid)
    session = load_session(conn, pid, sid)
    if session["status"] != "completed":
        return redirect(f"/profiles/{pid}/sessions/{sid}")
    return render(
        request,
        "summary.html",
        profile=profile,
        session=session,
        **sessions.summary(conn, sid),
    )
