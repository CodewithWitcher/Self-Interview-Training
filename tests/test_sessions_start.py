from app import llm, questions
from tests.helpers import ready_profile, topic_row


def start(client, pid, topic_ids, count=5, difficulty="easy", model="fake:fake", **extra):
    data = {
        "topics": [str(t) for t in topic_ids],
        "count": str(count),
        "difficulty": difficulty,
        "model": model,
    }
    data.update(extra)
    return client.post(f"/profiles/{pid}/sessions", data=data, follow_redirects=False)


def count_generate_calls(monkeypatch):
    calls = []
    real = questions.generate

    def spy(*args, **kwargs):
        calls.append(args[1]["name"])
        return real(*args, **kwargs)

    monkeypatch.setattr(questions, "generate", spy)
    return calls


def test_five_questions_over_two_topics_alternate(client, conn):
    pid = ready_profile(client)
    py, sql = topic_row(conn, pid, "Python"), topic_row(conn, pid, "SQL")
    r = start(client, pid, [py["id"], sql["id"]])
    assert r.status_code == 303
    sid = int(r.headers["location"].rsplit("/", 1)[1])
    rows = conn.execute(
        "SELECT a.ord, q.topic_id, a.status, a.is_review, "
        "(SELECT count(*) FROM turns WHERE attempt_id = a.id AND level = 0) AS t0, "
        "(SELECT prompt FROM turns WHERE attempt_id = a.id) AS prompt, q.text "
        "FROM attempts a JOIN questions q ON q.id = a.question_id WHERE a.session_id = ? ORDER BY a.ord",
        (sid,),
    ).fetchall()
    assert [r["ord"] for r in rows] == [1, 2, 3, 4, 5]
    # Python has the higher weight, so it is visited first.
    assert [r["topic_id"] for r in rows] == [py["id"], sql["id"], py["id"], sql["id"], py["id"]]
    assert all(r["t0"] == 1 and r["prompt"] == r["text"] for r in rows)
    assert all(r["status"] == "pending" and r["is_review"] == 0 for r in rows)
    page = client.get(f"/profiles/{pid}/sessions/{sid}")
    assert page.status_code == 200
    assert "Question 1 of 5" in page.text


def test_stored_questions_are_used_before_generating(client, conn, settings, monkeypatch):
    pid = ready_profile(client)
    py = topic_row(conn, pid, "Python")
    questions.generate(conn, py, 3, "easy", "fake", "fake", client.app.state.rng, settings)
    calls = count_generate_calls(monkeypatch)
    r = start(client, pid, [py["id"]], count=3)
    assert r.status_code == 303
    assert calls == []
    calls.clear()
    # The three stored questions are now attempted, so a new session must generate.
    sid = int(r.headers["location"].rsplit("/", 1)[1])
    with conn:
        conn.execute("UPDATE sessions SET status = 'completed' WHERE id = ?", (sid,))
    start(client, pid, [py["id"]], count=3)
    assert calls == ["Python"]


def test_second_start_redirects_to_active_session(client, conn):
    pid = ready_profile(client)
    py = topic_row(conn, pid, "Python")
    first = start(client, pid, [py["id"]], count=3).headers["location"]
    second = start(client, pid, [py["id"]], count=3)
    assert second.status_code == 303
    assert second.headers["location"] == first
    assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1


def test_topic_with_weight_zero_is_not_offered(client, conn):
    pid = ready_profile(client)
    sql = topic_row(conn, pid, "SQL")
    client.post(f"/profiles/{pid}/topics/{sql['id']}", data={"weight": "0"})
    page = client.get(f"/profiles/{pid}").text
    assert f'value="{sql["id"]}"' not in page
    assert "Python" in page
    r = start(client, pid, [sql["id"]], count=3)
    assert r.status_code == 422


def test_generation_failing_everywhere_creates_nothing(client, conn, monkeypatch):
    pid = ready_profile(client)
    py = topic_row(conn, pid, "Python")

    def down(*a, **k):
        raise llm.LLMUnavailable("Ollama is not running at x.")

    monkeypatch.setattr(llm, "chat", down)
    r = start(client, pid, [py["id"]], count=3)
    assert r.status_code == 422
    assert "could not be reached" in r.text
    assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0


def test_generation_failing_for_one_topic_starts_shorter(client, conn, monkeypatch):
    pid = ready_profile(client)
    py, sql = topic_row(conn, pid, "Python"), topic_row(conn, pid, "SQL")
    real = llm.chat

    def sql_down(provider, model, system, user, schema, **kw):
        if "Topic: SQL" in user:
            raise llm.LLMOutputError("bad")
        return real(provider, model, system, user, schema, **kw)

    monkeypatch.setattr(llm, "chat", sql_down)
    r = start(client, pid, [py["id"], sql["id"]], count=5)
    assert r.status_code == 303
    assert conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 3
    page = client.get(r.headers["location"], follow_redirects=True).text
    assert "No questions for SQL" in page
    assert "Found 3 of 5 questions" in page


def test_form_preselects_last_used_model(client, conn):
    pid = ready_profile(client)
    py = topic_row(conn, pid, "Python")
    page = client.get(f"/profiles/{pid}").text
    assert '<option value="fake:fake" selected>' in page
    start(client, pid, [py["id"]], count=3)
    with conn:
        conn.execute("UPDATE sessions SET status = 'completed'")
    page = client.get(f"/profiles/{pid}").text
    assert '<option value="fake:fake" selected>' in page


def test_preselect_prefers_last_session_over_default(conn, client, settings):
    from dataclasses import replace

    from app.llm import ModelOption
    from app.sessions import preselected_model

    pid = ready_profile(client)
    real = replace(settings, dev_fake=False)
    options = [
        ModelOption("ollama", "llama3.1:8b", "Local", True),
        ModelOption("anthropic", "claude-haiku-5-5", "Cloud", False),
    ]
    assert preselected_model(conn, pid, real, options) == "ollama:llama3.1:8b"
    with conn:
        conn.execute(
            "INSERT INTO sessions (profile_id, provider, model, difficulty, status, created_at) "
            "VALUES (?, 'anthropic', 'claude-haiku-5-5', 'easy', 'completed', 'x')",
            (pid,),
        )
    assert preselected_model(conn, pid, real, options) == "anthropic:claude-haiku-5-5"


def test_invalid_form_keeps_choices(client, conn):
    pid = ready_profile(client)
    py = topic_row(conn, pid, "Python")
    r = start(client, pid, [py["id"]], count=4)
    assert r.status_code == 422
    assert "Choose 3, 5 or 10" in r.text
    r = start(client, pid, [], count=3)
    assert "Choose at least one topic" in r.text


def test_other_profiles_session_is_404(client, conn):
    a = ready_profile(client, "A")
    b = ready_profile(client, "B")
    py = topic_row(conn, a, "Python")
    loc = start(client, a, [py["id"]], count=3).headers["location"]
    sid = loc.rsplit("/", 1)[1]
    assert client.get(f"/profiles/{b}/sessions/{sid}").status_code == 404
