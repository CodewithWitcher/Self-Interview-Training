"""Readiness and history of a profile (F13, PS 7.4, DM 9)."""

import sqlite3
from datetime import UTC, date, datetime, time

from app.scoring import attempt_score, readiness, topic_score, weakest_dimension

LATEST_ATTEMPTS = """
SELECT q.id AS question_id, q.topic_id, a.id AS attempt_id, a.score, a.completed_at
FROM questions q
JOIN topics t ON t.id = q.topic_id
JOIN attempts a ON a.id = (
  SELECT a2.id
  FROM attempts a2
  WHERE a2.question_id = q.id AND a2.status = 'done'
  ORDER BY a2.completed_at DESC, a2.id DESC
  LIMIT 1
)
WHERE t.profile_id = ? AND t.weight > 0
"""


def parse_utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def end_of(today: date) -> datetime:
    """The time readiness is computed at, derived from app.state.today."""
    return datetime.combine(today, time(23, 59, 59), tzinfo=UTC)


def profile_progress(conn: sqlite3.Connection, profile_id: int, today: date) -> dict:
    now = end_of(today)
    rows = conn.execute(LATEST_ATTEMPTS, (profile_id,)).fetchall()
    topics = conn.execute(
        "SELECT * FROM topics WHERE profile_id = ? AND weight > 0 "
        "ORDER BY weight DESC, name COLLATE NOCASE",
        (profile_id,),
    ).fetchall()
    by_topic: dict[int, list] = {t["id"]: [] for t in topics}
    for r in rows:
        by_topic[r["topic_id"]].append((r["score"], parse_utc(r["completed_at"])))
    topic_list = []
    for t in topics:
        tr = topic_score(by_topic[t["id"]], now)
        topic_list.append({"topic": t, "result": tr})
    value = readiness((t["topic"]["weight"], t["result"]) for t in topic_list)
    attempt_ids = [r["attempt_id"] for r in rows]
    turns = []
    if attempt_ids:
        marks = ",".join("?" * len(attempt_ids))
        turns = conn.execute(
            f"SELECT * FROM turns WHERE attempt_id IN ({marks})", attempt_ids
        ).fetchall()
    return {
        "readiness": value,
        "has_history": bool(rows),
        "topics": topic_list,
        "weakest": weakest_dimension(turns),
        "sessions": session_history(conn, profile_id),
    }


def readiness_value(conn: sqlite3.Connection, profile_id: int, today: date) -> int | None:
    rows = conn.execute(LATEST_ATTEMPTS, (profile_id,)).fetchall()
    if not rows:
        return None
    return profile_progress(conn, profile_id, today)["readiness"]


def session_history(conn: sqlite3.Connection, profile_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT s.*, (SELECT count(*) FROM attempts a WHERE a.session_id = s.id) AS questions "
        "FROM sessions s WHERE s.profile_id = ? AND s.status = 'completed' "
        "ORDER BY s.completed_at DESC, s.id DESC",
        (profile_id,),
    ).fetchall()
    out = []
    for s in rows:
        scores = [
            r[0]
            for r in conn.execute(
                "SELECT score FROM attempts WHERE session_id = ? AND score IS NOT NULL", (s["id"],)
            )
        ]
        out.append(
            {
                "session": s,
                "date": (s["completed_at"] or s["created_at"])[:10],
                "average": attempt_score(scores) if scores else None,
            }
        )
    return out
