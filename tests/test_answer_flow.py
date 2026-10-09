from app import db, evaluation, llm
from tests.helpers import answer, current, ready_profile, skip, start_session


def setup(client, conn, topics=("Python",), count=3):
    pid = ready_profile(client)
    sid = start_session(client, conn, pid, topics, count)
    return pid, sid


def page(client, pid, sid, aid):
    return client.get(f"/profiles/{pid}/sessions/{sid}/attempts/{aid}").text


def test_plain_answer_shows_75_and_four_dimensions(client, conn):
    pid, sid = setup(client, conn)
    aid, _ = current(conn, sid)
    r = answer(client, conn, pid, sid, "A plain answer.")
    assert r.status_code == 303
    text = page(client, pid, sid, aid)
    assert "Score 75" in text
    for dim in ("Correctness: 3 of 4", "Depth: 3 of 4", "Clarity: 3 of 4", "Structure: 3 of 4"):
        assert dim in text
    assert "Fake strength." in text and "Fake gap." in text
    assert "Fake feedback." in text
    assert "Covered: Fake key point 1" in text and "Missed: Fake key point 2" in text
    row = conn.execute("SELECT * FROM turns WHERE attempt_id = ?", (aid,)).fetchone()
    assert row["eval_model"] == "fake:fake"
    assert conn.execute("SELECT status, score FROM attempts WHERE id = ?", (aid,)).fetchone()[
        :
    ] == (
        "done",
        75,
    )


def test_followup_twice_gives_levels_1_and_2_never_3(client, conn):
    pid, sid = setup(client, conn)
    aid, _ = current(conn, sid)
    answer(client, conn, pid, sid, "first #followup #strong")
    _, turn = current(conn, sid)
    assert turn["level"] == 1 and turn["prompt"] == "Fake follow-up: tell me more."
    answer(client, conn, pid, sid, "second #followup #weak")
    _, turn = current(conn, sid)
    assert turn["level"] == 2
    answer(client, conn, pid, sid, "third #followup")
    levels = [r[0] for r in conn.execute("SELECT level FROM turns WHERE attempt_id = ?", (aid,))]
    assert levels == [0, 1, 2]
    # The attempt score is the mean of 100, 25 and 75.
    assert conn.execute("SELECT score FROM attempts WHERE id = ?", (aid,)).fetchone()[0] == 67
    text = page(client, pid, sid, aid)
    assert "Follow-up 1:" in text and "Follow-up 2:" in text
    assert "Question score 67" in text


def test_down_keeps_answer_and_retry_succeeds(client, conn, monkeypatch):
    pid, sid = setup(client, conn)
    aid, turn = current(conn, sid)
    r = answer(client, conn, pid, sid, "My answer #down")
    assert r.status_code == 303 and "error=unavailable" in r.headers["location"]
    text = client.get(r.headers["location"]).text
    assert "could not be reached" in text
    assert "My answer #down" in text
    assert "Retry scoring" in text and "Change model" in text
    saved = conn.execute(
        "SELECT answer_text, score FROM turns WHERE id = ?", (turn["id"],)
    ).fetchone()
    assert saved[0] == "My answer #down" and saved[1] is None
    # The model comes back.
    real = llm.chat

    def fixed(provider, model, system, user, schema, **kw):
        return real(provider, model, system, user.replace("#down", ""), schema, **kw)

    monkeypatch.setattr(llm, "chat", fixed)
    r = client.post(
        f"/profiles/{pid}/sessions/{sid}/attempts/{aid}/evaluate", follow_redirects=False
    )
    assert r.status_code == 303 and "error" not in r.headers["location"]
    assert conn.execute("SELECT score FROM turns WHERE id = ?", (turn["id"],)).fetchone()[0] == 75


def test_invalid_behaves_the_same(client, conn, monkeypatch):
    pid, sid = setup(client, conn)
    aid, turn = current(conn, sid)
    r = answer(client, conn, pid, sid, "x #invalid")
    assert "error=output" in r.headers["location"]
    assert "unusable reply" in client.get(r.headers["location"]).text
    real = llm.chat
    monkeypatch.setattr(
        llm, "chat", lambda p, m, s, u, sc, **kw: real(p, m, s, u.replace("#invalid", ""), sc, **kw)
    )
    client.post(f"/profiles/{pid}/sessions/{sid}/attempts/{aid}/evaluate")
    assert conn.execute("SELECT score FROM turns WHERE id = ?", (turn["id"],)).fetchone()[0] == 75


def test_skip_scores_zero_and_shows_reference(client, conn):
    pid, sid = setup(client, conn)
    aid, turn = current(conn, sid)
    before = page(client, pid, sid, aid)
    ref = conn.execute(
        "SELECT reference_answer FROM questions q JOIN attempts a ON a.question_id = q.id WHERE a.id = ?",
        (aid,),
    ).fetchone()[0]
    assert ref not in before
    assert skip(client, conn, pid, sid).status_code == 303
    row = conn.execute("SELECT * FROM turns WHERE id = ?", (turn["id"],)).fetchone()
    assert (row["skipped"], row["score"], row["answer_text"]) == (1, 0, "")
    assert (
        conn.execute("SELECT count(*) FROM turns WHERE attempt_id = ?", (aid,)).fetchone()[0] == 1
    )
    after = page(client, pid, sid, aid)
    assert ref in after and "Score 0" in after


def test_reference_hidden_until_done(client, conn):
    pid, sid = setup(client, conn)
    aid, _ = current(conn, sid)
    ref = conn.execute(
        "SELECT reference_answer FROM questions q JOIN attempts a ON a.question_id = q.id WHERE a.id = ?",
        (aid,),
    ).fetchone()[0]
    answer(client, conn, pid, sid, "x #followup")
    assert ref not in page(client, pid, sid, aid)
    answer(client, conn, pid, sid, "y")
    assert ref in page(client, pid, sid, aid)


def test_empty_and_long_answers_are_rejected_with_text_kept(client, conn):
    pid, sid = setup(client, conn)
    r = answer(client, conn, pid, sid, "   ")
    assert r.status_code == 422
    long = "z" * 5001
    r = answer(client, conn, pid, sid, long)
    assert r.status_code == 422
    assert long in r.text
    assert "5,000" in r.text
    _, turn = current(conn, sid)
    assert turn["answer_text"] is None


def test_double_submit_creates_no_second_turn(client, conn):
    pid, sid = setup(client, conn)
    aid, turn = current(conn, sid)
    data = {"text": "x #followup", "turn_id": str(turn["id"])}
    url = f"/profiles/{pid}/sessions/{sid}/attempts/{aid}/answer"
    client.post(url, data=data)
    r = client.post(url, data=data, follow_redirects=False)
    assert r.status_code == 303
    rows = conn.execute(
        "SELECT level, answer_text FROM turns WHERE attempt_id = ?", (aid,)
    ).fetchall()
    assert [(r[0], r[1]) for r in rows] == [(0, "x #followup"), (1, None)]


def test_resume_probe_question_shows_excerpt(client, conn):
    pid = ready_profile(client)
    sid = start_session(client, conn, pid, ("Resume deep-dive",), 3)
    aid, _ = current(conn, sid)
    context = conn.execute(
        "SELECT context FROM questions q JOIN attempts a ON a.question_id = q.id WHERE a.id = ?",
        (aid,),
    ).fetchone()[0]
    text = page(client, pid, sid, aid)
    assert "From your resume" in text
    first_line = context.splitlines()[0]
    assert first_line in text


def test_badges(client, conn):
    pid, sid = setup(client, conn)
    aid, _ = current(conn, sid)
    assert "Local: nothing leaves this computer" in page(client, pid, sid, aid)
    with conn:
        conn.execute("UPDATE sessions SET provider = 'anthropic', model = 'claude-opus-5-5'")
    text = page(client, pid, sid, aid)
    assert "Cloud: your answers and resume excerpts are sent to Anthropic" in text
    assert "Local: nothing leaves" not in text


def test_no_transaction_is_open_during_model_call(client, conn, monkeypatch):
    pid, sid = setup(client, conn)
    opened = []
    real_connect = db.connect

    def tracking_connect(path):
        c = real_connect(path)
        opened.append(c)
        return c

    monkeypatch.setattr(db, "connect", tracking_connect)
    seen = []
    real_chat = llm.chat

    def spy(*a, **kw):
        seen.append([c.in_transaction for c in opened])
        return real_chat(*a, **kw)

    monkeypatch.setattr(llm, "chat", spy)
    answer(client, conn, pid, sid, "x")
    assert seen and all(not any(states) for states in seen)
    assert opened, "the request used no tracked connection"


def test_normalise_evaluation_rules():
    from app.prompts import Evaluation

    e = Evaluation(
        strengths=[" a ", "", "b", "c", "d"],
        gaps=["", " g "],
        key_points_hit=[3, 1, 1, 9, 0],
        correctness=3,
        depth=3,
        clarity=3,
        structure=3,
        feedback=" ok ",
        follow_up="x" * 401,
    )
    out = evaluation.normalise_evaluation(e, 0, 3)
    assert out.strengths == ["a", "b", "c"] and out.gaps == ["g"]
    assert out.key_points_hit == [1, 3]
    assert out.follow_up == "" and out.feedback == "ok"
    assert (
        evaluation.normalise_evaluation(
            e.model_copy(update={"follow_up": "why?"}), 1, 3
        ).key_points_hit
        == []
    )
    assert (
        evaluation.normalise_evaluation(e.model_copy(update={"follow_up": "why?"}), 2, 3).follow_up
        == ""
    )
    import pytest

    with pytest.raises(llm.InvalidReply):
        evaluation.normalise_evaluation(e.model_copy(update={"feedback": " "}), 0, 3)
