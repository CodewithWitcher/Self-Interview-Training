from datetime import date, timedelta

import pytest

from app.scoring import srs_next
from tests.conftest import TODAY, make_client
from tests.helpers import answer, current, ready_profile, start_session, topic_row

D = date.fromisoformat


@pytest.mark.parametrize(
    ("today", "step", "score", "new_step", "due"),
    [
        ("2026-10-12", None, 40, 0, "2026-10-13"),
        ("2026-10-13", 0, 80, 1, "2026-10-16"),
        ("2026-10-16", 1, 60, 1, "2026-10-19"),
        ("2026-10-19", 1, 90, 2, "2026-10-26"),
        ("2026-10-26", 2, 30, 0, "2026-10-27"),
        ("2026-10-26", 3, 75, None, None),
        ("2026-10-26", None, 75, None, None),
    ],
)
def test_table(today, step, score, new_step, due):
    assert srs_next(step, score, D(today)) == (new_step, D(due) if due else None)


def test_full_ladder_retires_after_four_passes():
    day = D("2026-10-12")
    step, due = srs_next(None, 40, day)
    gaps = []
    while step is not None:
        prev = due
        step, due = srs_next(step, 90, prev)
        if due:
            gaps.append((due - prev).days)
    assert gaps == [3, 7, 14]
    # First failure on 10-12, then due 10-13, 10-16, 10-23 and 11-06, then retired: 25 days.
    assert (D("2026-11-06") - day).days == 25


def test_weak_answer_is_due_next_day_not_before(client, conn, settings):
    pid = ready_profile(client)
    sid = start_session(client, conn, pid, ("Python",), 3)
    aid, _ = current(conn, sid)
    answer(client, conn, pid, sid, "x #weak")
    q = conn.execute(
        "SELECT q.srs_step, q.srs_due FROM questions q JOIN attempts a ON a.question_id = q.id WHERE a.id = ?",
        (aid,),
    ).fetchone()
    assert (q[0], q[1]) == (0, (TODAY + timedelta(days=1)).isoformat())
    answer(client, conn, pid, sid, "y")  # 75 stays out of review
    answer(client, conn, pid, sid, "z")
    assert "Due today: 0" in client.get(f"/profiles/{pid}").text
    with make_client(settings, today=TODAY + timedelta(days=1)) as later:
        assert "Due today: 1" in later.get(f"/profiles/{pid}").text


def test_session_takes_at_most_half_reviews(client, conn, settings):
    pid = ready_profile(client)
    sid = start_session(client, conn, pid, ("Python", "SQL"), 5)
    for _ in range(5):
        answer(client, conn, pid, sid, "x #weak")
    with make_client(settings, today=TODAY + timedelta(days=1)) as later:
        sid2 = start_session(later, conn, pid, ("Python", "SQL"), 5)
    rows = conn.execute(
        "SELECT is_review FROM attempts WHERE session_id = ? ORDER BY ord", (sid2,)
    ).fetchall()
    assert [r[0] for r in rows] == [1, 1, 0, 0, 0]


def test_reviews_restricted_to_chosen_topics(client, conn, settings):
    pid = ready_profile(client)
    sid = start_session(client, conn, pid, ("Python",), 3)
    for _ in range(3):
        answer(client, conn, pid, sid, "x #weak")
    with make_client(settings, today=TODAY + timedelta(days=1)) as later:
        sid2 = start_session(later, conn, pid, ("SQL",), 3)
    reviews = conn.execute(
        "SELECT count(*) FROM attempts WHERE session_id = ? AND is_review = 1", (sid2,)
    ).fetchone()[0]
    assert reviews == 0


def test_review_only_with_nothing_due_creates_nothing(client, conn):
    pid = ready_profile(client)
    py = topic_row(conn, pid, "Python")
    r = client.post(
        f"/profiles/{pid}/sessions",
        data={
            "topics": [str(py["id"])],
            "count": "3",
            "difficulty": "easy",
            "model": "fake:fake",
            "review_only": "1",
        },
    )
    assert r.status_code == 422
    assert "Nothing is due for review" in r.text
    assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0


def test_review_only_uses_all_topics(client, conn, settings):
    pid = ready_profile(client)
    sid = start_session(client, conn, pid, ("Python", "SQL"), 3)
    for _ in range(3):
        answer(client, conn, pid, sid, "x #weak")
    with make_client(settings, today=TODAY + timedelta(days=1)) as later:
        r = later.post(
            f"/profiles/{pid}/sessions",
            data={"count": "5", "difficulty": "hard", "model": "fake:fake", "review_only": "1"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        sid2 = int(r.headers["location"].rsplit("/", 1)[1])
    rows = conn.execute("SELECT is_review FROM attempts WHERE session_id = ?", (sid2,)).fetchall()
    assert [r[0] for r in rows] == [1, 1, 1]
