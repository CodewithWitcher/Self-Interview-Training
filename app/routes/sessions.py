"""Practice sessions: start, question page, answer, scoring, follow-ups, end (F4 to F9)."""

import sqlite3

from fastapi import APIRouter, HTTPException, Request

from app import sessions
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
    turns = conn.execute(
        "SELECT * FROM turns WHERE attempt_id = ? ORDER BY level", (attempt["id"],)
    ).fetchall()
    total = conn.execute(
        "SELECT count(*) FROM attempts WHERE session_id = ?", (session["id"],)
    ).fetchone()[0]
    context = {
        "profile": profile,
        "session": session,
        "attempt": attempt,
        "question": question,
        "turns": turns,
        "total": total,
        "messages": take_flash(request, session["id"]),
    }
    context.update(extra)
    return render(request, "attempt.html", status_code, **context)
