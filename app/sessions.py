"""Session life cycle (F4, F8, AR 6)."""

import sqlite3
from dataclasses import dataclass, field
from datetime import date

from app import llm, questions
from app.config import Settings
from app.db import utc_now
from app.llm import ModelOption
from app.scoring import QUESTIONS_PER_CALL


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
