from app.sessions import finish_attempt
from tests.conftest import make_client
from tests.helpers import answer, current, ready_profile, skip, start_session


def test_new_client_on_same_data_lands_on_question_3(client, conn, settings):
    pid = ready_profile(client)
    sid = start_session(client, conn, pid, ("Python", "SQL"), 5)
    answer(client, conn, pid, sid, "one")
    answer(client, conn, pid, sid, "two")
    third, _ = current(conn, sid)
    with make_client(settings) as fresh:
        home = fresh.get(f"/profiles/{pid}").text
        assert "Continue session, question 3 of 5" in home
        r = fresh.get(f"/profiles/{pid}/sessions/{sid}", follow_redirects=False)
        assert r.headers["location"] == f"/profiles/{pid}/sessions/{sid}/attempts/{third}"
        assert "Question 3 of 5" in fresh.get(r.headers["location"]).text


def test_each_stored_state_renders_its_page(client, conn):
    pid = ready_profile(client)
    sid = start_session(client, conn, pid)
    aid, _ = current(conn, sid)
    url = f"/profiles/{pid}/sessions/{sid}/attempts/{aid}"
    assert "Submit answer" in client.get(url).text
    answer(client, conn, pid, sid, "x #down")
    text = client.get(url).text  # No error code in the URL, as after a restart.
    assert "Retry scoring" in text and "Submit answer" not in text
    assert "saved" in text
    with conn:
        conn.execute("DELETE FROM turns WHERE attempt_id = ?", (aid,))
        conn.execute(
            "INSERT INTO turns (attempt_id, level, prompt, answer_text, score, s_correctness, "
            "s_depth, s_clarity, s_structure) VALUES (?, 0, 'Q', 'A', 50, 2, 2, 2, 2)",
            (aid,),
        )
        finish_attempt(conn, aid, client.app.state.today())
    text = client.get(url).text
    assert "Reference answer" in text and "Next question" in text


def test_finishing_last_attempt_completes_session(client, conn):
    pid = ready_profile(client)
    sid = start_session(client, conn, pid)
    for _ in range(3):
        answer(client, conn, pid, sid, "x")
    row = conn.execute("SELECT status, completed_at FROM sessions WHERE id = ?", (sid,)).fetchone()
    assert row[0] == "completed" and row[1]
    r = client.get(f"/profiles/{pid}/sessions/{sid}", follow_redirects=False)
    assert r.headers["location"].endswith("/summary")


def test_end_early_rules(client, conn):
    pid = ready_profile(client)
    sid = start_session(client, conn, pid, ("Python", "SQL"), 5)
    answer(client, conn, pid, sid, "done one")  # attempt 1 done, 75
    answer(client, conn, pid, sid, "partial #followup #strong")  # attempt 2 has a scored turn
    a2, _ = current(conn, sid)
    r = client.post(f"/profiles/{pid}/sessions/{sid}/end", follow_redirects=False)
    assert r.headers["location"] == f"/profiles/{pid}/sessions/{sid}/summary"
    attempts = conn.execute(
        "SELECT id, status, score FROM attempts WHERE session_id = ? ORDER BY ord", (sid,)
    ).fetchall()
    assert [(a["status"], a["score"]) for a in attempts] == [("done", 75), ("done", 100)]
    assert conn.execute("SELECT count(*) FROM turns WHERE attempt_id = ?", (a2,)).fetchone()[0] == 1
    assert (
        conn.execute("SELECT status FROM sessions WHERE id = ?", (sid,)).fetchone()[0]
        == "completed"
    )
    # The unanswered questions return to the bank.
    free = conn.execute(
        "SELECT count(*) FROM questions q WHERE NOT EXISTS (SELECT 1 FROM attempts a WHERE a.question_id = q.id)"
    ).fetchone()[0]
    assert free >= 3


def test_end_with_unscored_answer_discards_it(client, conn):
    pid = ready_profile(client)
    sid = start_session(client, conn, pid)
    answer(client, conn, pid, sid, "x")
    answer(client, conn, pid, sid, "y #down")
    client.post(f"/profiles/{pid}/sessions/{sid}/end")
    assert (
        conn.execute("SELECT count(*) FROM attempts WHERE session_id = ?", (sid,)).fetchone()[0]
        == 1
    )
    assert (
        conn.execute("SELECT count(*) FROM turns WHERE answer_text = 'y #down'").fetchone()[0] == 0
    )


def test_end_with_nothing_scored_deletes_session(client, conn):
    pid = ready_profile(client)
    sid = start_session(client, conn, pid)
    r = client.post(f"/profiles/{pid}/sessions/{sid}/end", follow_redirects=False)
    assert r.headers["location"] == f"/profiles/{pid}?notice=session_ended"
    assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0
    assert "Nothing was scored" in client.get(r.headers["location"]).text


def test_summary_shows_attempts_average_and_weakest(client, conn):
    pid = ready_profile(client)
    sid = start_session(client, conn, pid)
    answer(client, conn, pid, sid, "x #strong")
    skip(client, conn, pid, sid)
    answer(client, conn, pid, sid, "x #wrong")
    text = client.get(f"/profiles/{pid}/sessions/{sid}/summary").text
    texts = [
        r[0]
        for r in conn.execute(
            "SELECT q.text FROM attempts a JOIN questions q ON q.id = a.question_id WHERE a.session_id = ?",
            (sid,),
        )
    ]
    assert all(t in text for t in texts)
    assert "Session average 40" in text  # mean of 100, 0, 20
    assert "Weakest rubric dimension: <strong>correctness</strong>" in text


def test_model_change_records_new_eval_model(client, conn):
    pid = ready_profile(client)
    sid = start_session(client, conn, pid)
    with conn:  # Pretend the session started on another model.
        conn.execute("UPDATE sessions SET model = 'other' WHERE id = ?", (sid,))
    aid, _ = current(conn, sid)
    r = client.post(
        f"/profiles/{pid}/sessions/{sid}/model",
        data={"model": "fake:fake", "back": str(aid)},
        follow_redirects=False,
    )
    assert r.headers["location"].startswith(f"/profiles/{pid}/sessions/{sid}/attempts/{aid}")
    answer(client, conn, pid, sid, "x")
    assert (
        conn.execute("SELECT eval_model FROM turns WHERE attempt_id = ?", (aid,)).fetchone()[0]
        == "fake:fake"
    )


def test_bad_model_change_is_rejected(client, conn):
    pid = ready_profile(client)
    sid = start_session(client, conn, pid)
    r = client.post(f"/profiles/{pid}/sessions/{sid}/model", data={"model": "ollama:x"})
    assert r.status_code == 422
