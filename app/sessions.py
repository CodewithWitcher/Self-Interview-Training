"""Session life cycle (F4, F8, AR 6)."""

import sqlite3
from dataclasses import dataclass, field
from datetime import date

from app import llm, questions
from app.config import Settings
from app.db import utc_now
from app.llm import ModelOption
from app.scoring import (
    MAX_FOLLOW_UPS,
    QUESTIONS_PER_CALL,
    attempt_score,
    srs_next,
    weakest_dimension,
)


def last_used_model(conn: sqlite3.Connection, profile_id: int) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT provider, model FROM sessions WHERE profile_id = ? ORDER BY id DESC LIMIT 1",
        (profile_id,),
    ).fetchone()
    return (row["provider"], row["model"]) if row else None


def preselected_model(
    conn: sqlite3.Connection, profile_id: int, settings: Settings, options: list[ModelOption]
) -> str:
    """The picker value to preselect: the profile's last choice, else the configured default (F9.1)."""
    values = [o.value for o in options]
    last = last_used_model(conn, profile_id)
    if last and f"{last[0]}:{last[1]}" in values:
        return f"{last[0]}:{last[1]}"
    if settings.dev_fake:
        return "fake:fake"
    if settings.default_provider == "anthropic":
        return f"anthropic:{settings.anthropic_model}"
    preferred = f"ollama:{settings.ollama_model}"
    if preferred in values:
        return preferred
    local = [o.value for o in options if o.is_local]
    return local[0] if local else preferred


COUNTS = (3, 5, 10)
DIFFICULTIES = ("easy", "medium", "hard")
GENERATE_CALLS_PER_TOPIC = 2


@dataclass
class Composition:
    """The questions of a new session, in order, and what to tell the user."""

    items: list[tuple[int, bool]] = field(default_factory=list)  # (question id, is review)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (topic name, reason)
    wanted: int = 0


def active_topics(conn: sqlite3.Connection, profile_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM topics WHERE profile_id = ? AND weight > 0 "
        "ORDER BY weight DESC, name COLLATE NOCASE",
        (profile_id,),
    ).fetchall()


def unattempted(conn: sqlite3.Connection, topic_id: int, difficulty: str) -> list[int]:
    rows = conn.execute(
        "SELECT q.id FROM questions q WHERE q.topic_id = ? AND q.difficulty = ? "
        "AND NOT EXISTS (SELECT 1 FROM attempts a WHERE a.question_id = q.id) ORDER BY q.id",
        (topic_id, difficulty),
    ).fetchall()
    return [r["id"] for r in rows]


def share_slots(topics: list[sqlite3.Row], slots: int) -> dict[int, int]:
    """Share slots among topics in rounds, one per topic per round, in the given order."""
    shares = {t["id"]: 0 for t in topics}
    for i in range(slots):
        shares[topics[i % len(topics)]["id"]] += 1
    return shares


def compose(
    conn: sqlite3.Connection,
    profile_id: int,
    topic_ids: list[int],
    n: int,
    difficulty: str,
    provider: str,
    model: str,
    rng,
    settings: Settings,
    today: date,
    review_only: bool = False,
) -> Composition:
    """Choose the questions of a new session by the rules of PS 6. May call the model."""
    result = Composition(wanted=n)
    chosen = [t for t in active_topics(conn, profile_id) if t["id"] in set(topic_ids)]
    reviews = due_questions(conn, profile_id, today)
    if not review_only:
        allowed = {t["id"] for t in chosen}
        reviews = [r for r in reviews if r["topic_id"] in allowed]
    reviews = reviews[: n if review_only else n // 2]
    result.items = [(r["id"], True) for r in reviews]
    if review_only or not chosen:
        return result
    shares = share_slots(chosen, n - len(reviews))
    per_topic: list[list[int]] = []
    for topic in chosen:
        want = shares[topic["id"]]
        if want == 0:
            continue
        ids = unattempted(conn, topic["id"], difficulty)[:want]
        calls = 0
        while len(ids) < want and calls < GENERATE_CALLS_PER_TOPIC:
            calls += 1
            ask = min(QUESTIONS_PER_CALL, want - len(ids))
            try:
                ids += questions.generate(
                    conn, topic, ask, difficulty, provider, model, rng, settings
                )[: want - len(ids)]
            except (llm.LLMError, questions.GenerationError) as exc:
                reason = f"{exc.title}. {exc}" if isinstance(exc, llm.LLMError) else str(exc)
                result.failed.append((topic["name"], reason))
                break
        per_topic.append(ids)
    for round_ in range(max((len(ids) for ids in per_topic), default=0)):
        for ids in per_topic:
            if round_ < len(ids):
                result.items.append((ids[round_], False))
    return result


def due_questions(conn: sqlite3.Connection, profile_id: int, today: date) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT q.* FROM questions q JOIN topics t ON t.id = q.topic_id "
        "WHERE t.profile_id = ? AND q.srs_due IS NOT NULL AND q.srs_due <= ? "
        "ORDER BY q.srs_due, q.id",
        (profile_id, today.isoformat()),
    ).fetchall()


def active_session(conn: sqlite3.Connection, profile_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM sessions WHERE profile_id = ? AND status = 'active'", (profile_id,)
    ).fetchone()


def start(
    conn: sqlite3.Connection,
    profile_id: int,
    items: list[tuple[int, bool]],
    provider: str,
    model: str,
    difficulty: str,
) -> int:
    """Insert the session, its attempts and their level 0 turns in one transaction."""
    with conn:
        sid = conn.execute(
            "INSERT INTO sessions (profile_id, provider, model, difficulty, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (profile_id, provider, model, difficulty, utc_now()),
        ).lastrowid
        for ord_, (qid, is_review) in enumerate(items, start=1):
            text = conn.execute("SELECT text FROM questions WHERE id = ?", (qid,)).fetchone()[0]
            aid = conn.execute(
                "INSERT INTO attempts (session_id, question_id, ord, is_review) VALUES (?, ?, ?, ?)",
                (sid, qid, ord_, int(is_review)),
            ).lastrowid
            conn.execute(
                "INSERT INTO turns (attempt_id, level, prompt) VALUES (?, 0, ?)", (aid, text)
            )
    return sid


def current_attempt(conn: sqlite3.Connection, session_id: int) -> sqlite3.Row | None:
    """The first attempt, by position, that is not done."""
    return conn.execute(
        "SELECT * FROM attempts WHERE session_id = ? AND status != 'done' ORDER BY ord LIMIT 1",
        (session_id,),
    ).fetchone()


def progress(conn: sqlite3.Connection, session_id: int) -> tuple[int, int]:
    """(position of the current attempt, number of attempts)."""
    row = conn.execute(
        "SELECT count(*) AS total, min(CASE WHEN status != 'done' THEN ord END) AS pos "
        "FROM attempts WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return (row["pos"] or row["total"], row["total"])


def current_turn(conn: sqlite3.Connection, attempt_id: int) -> sqlite3.Row:
    return conn.execute(
        "SELECT * FROM turns WHERE attempt_id = ? ORDER BY level DESC LIMIT 1", (attempt_id,)
    ).fetchone()


def finish_attempt(conn: sqlite3.Connection, attempt_id: int, today: date) -> None:
    """Score the attempt from its turns, mark it done, update the review schedule, and complete
    the session when no unfinished attempt remains. Runs inside the caller's transaction."""
    scores = [
        r["score"]
        for r in conn.execute(
            "SELECT score FROM turns WHERE attempt_id = ? AND score IS NOT NULL", (attempt_id,)
        )
    ]
    now = utc_now()
    conn.execute(
        "UPDATE attempts SET status = 'done', score = ?, completed_at = ? WHERE id = ?",
        (attempt_score(scores), now, attempt_id),
    )
    attempt = conn.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
    update_schedule(conn, attempt["question_id"], attempt["score"], today)
    remaining = conn.execute(
        "SELECT count(*) FROM attempts WHERE session_id = ? AND status != 'done'",
        (attempt["session_id"],),
    ).fetchone()[0]
    if remaining == 0:
        conn.execute(
            "UPDATE sessions SET status = 'completed', completed_at = ? WHERE id = ?",
            (now, attempt["session_id"]),
        )


def update_schedule(conn: sqlite3.Connection, question_id: int, score: int, today: date) -> None:
    """Move the question along the review ladder (F12, PS 7.3)."""
    step = conn.execute("SELECT srs_step FROM questions WHERE id = ?", (question_id,)).fetchone()[0]
    new_step, due = srs_next(step, score, today)
    conn.execute(
        "UPDATE questions SET srs_step = ?, srs_due = ? WHERE id = ?",
        (new_step, due.isoformat() if due else None, question_id),
    )


def due_count(conn: sqlite3.Connection, profile_id: int, today: date) -> int:
    return len(due_questions(conn, profile_id, today))


def save_answer(conn: sqlite3.Connection, turn_id: int, attempt_id: int, text: str) -> None:
    """Transaction 1 of AR 6.1: the answer is stored before any model call."""
    with conn:
        conn.execute(
            "UPDATE turns SET answer_text = ?, answered_at = ? WHERE id = ? AND answer_text IS NULL",
            (text, utc_now(), turn_id),
        )
        conn.execute("UPDATE attempts SET status = 'active' WHERE id = ?", (attempt_id,))


def record_evaluation(conn: sqlite3.Connection, turn: sqlite3.Row, result, today: date) -> None:
    """Transaction 2 of AR 6.1: store the scores, then ask the follow-up or finish the attempt."""
    e = result.evaluation
    with conn:
        conn.execute(
            "UPDATE turns SET score = ?, s_correctness = ?, s_depth = ?, s_clarity = ?, "
            "s_structure = ?, eval_json = ?, eval_model = ? WHERE id = ?",
            (
                result.score,
                e.correctness,
                e.depth,
                e.clarity,
                e.structure,
                e.model_dump_json(),
                result.eval_model,
                turn["id"],
            ),
        )
        if e.follow_up and turn["level"] < MAX_FOLLOW_UPS:
            conn.execute(
                "INSERT INTO turns (attempt_id, level, prompt) VALUES (?, ?, ?)",
                (turn["attempt_id"], turn["level"] + 1, e.follow_up),
            )
        else:
            finish_attempt(conn, turn["attempt_id"], today)


def skip_turn(conn: sqlite3.Connection, turn: sqlite3.Row, today: date) -> None:
    with conn:
        conn.execute(
            "UPDATE turns SET answer_text = '', skipped = 1, answered_at = ?, score = 0, "
            "s_correctness = 0, s_depth = 0, s_clarity = 0, s_structure = 0 WHERE id = ?",
            (utc_now(), turn["id"]),
        )
        finish_attempt(conn, turn["attempt_id"], today)


def change_model(conn: sqlite3.Connection, session_id: int, provider: str, model: str) -> None:
    with conn:
        conn.execute(
            "UPDATE sessions SET provider = ?, model = ? WHERE id = ?",
            (provider, model, session_id),
        )


def end(conn: sqlite3.Connection, session_id: int, today: date) -> bool:
    """End a session early by the three rules of AR 6.4, in one transaction.

    Returns True when the session still exists and is completed, False when it was deleted.
    """
    with conn:
        attempts = conn.execute(
            "SELECT id FROM attempts WHERE session_id = ? AND status != 'done' ORDER BY ord",
            (session_id,),
        ).fetchall()
        for attempt in attempts:
            conn.execute(
                "DELETE FROM turns WHERE attempt_id = ? AND score IS NULL", (attempt["id"],)
            )
            scored = conn.execute(
                "SELECT count(*) FROM turns WHERE attempt_id = ?", (attempt["id"],)
            ).fetchone()[0]
            if scored:
                finish_attempt(conn, attempt["id"], today)
            else:
                conn.execute("DELETE FROM attempts WHERE id = ?", (attempt["id"],))
        left = conn.execute(
            "SELECT count(*) FROM attempts WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
        if left == 0:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return False
        conn.execute(
            "UPDATE sessions SET status = 'completed', completed_at = coalesce(completed_at, ?) "
            "WHERE id = ?",
            (utc_now(), session_id),
        )
    return True


def summary(conn: sqlite3.Connection, session_id: int) -> dict:
    attempts = conn.execute(
        "SELECT a.*, q.text, t.name AS topic_name FROM attempts a "
        "JOIN questions q ON q.id = a.question_id JOIN topics t ON t.id = q.topic_id "
        "WHERE a.session_id = ? ORDER BY a.ord",
        (session_id,),
    ).fetchall()
    turns = conn.execute(
        "SELECT tu.* FROM turns tu JOIN attempts a ON a.id = tu.attempt_id "
        "WHERE a.session_id = ? AND a.status = 'done'",
        (session_id,),
    ).fetchall()
    scores = [a["score"] for a in attempts if a["score"] is not None]
    return {
        "attempts": attempts,
        "average": attempt_score(scores) if scores else None,
        "weakest": weakest_dimension(turns),
    }
