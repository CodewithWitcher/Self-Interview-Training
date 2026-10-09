import json
import random

import numpy as np
import pytest

from app import llm, questions
from app.prompts import NewQuestion, QuestionBatch
from app.questions import drop_duplicates, normalise_batch
from tests.helpers import ready_profile, topic_row


def q(text="Q?", source=0, key_points=("a", "b", "c"), ref="R"):
    return NewQuestion(text=text, source=source, key_points=list(key_points), reference_answer=ref)


def batch(*qs):
    return QuestionBatch(questions=list(qs))


def test_rule_1_drops_empty_or_long_text_and_reference():
    out = normalise_batch(
        batch(q(" "), q("x" * 601), q("ok", ref=""), q("ok2", ref="r" * 2001), q("  keep  ")),
        5,
        "technical",
        [],
    )
    assert [c.text for c in out] == ["keep"]


def test_rule_2_key_points():
    out = normalise_batch(
        batch(
            q("A", key_points=[" a ", "", "k" * 301, "b", "c", "d", "e", "f", "g"]),
            q("B", key_points=["only one", " "]),
        ),
        5,
        "technical",
        [],
    )
    assert [c.text for c in out] == ["A"]
    assert out[0].key_points == ["a", "b", "c", "d", "e", "f"]


def test_rule_3_sources():
    tech = normalise_batch(batch(q("A", source=7)), 5, "technical", ["e1"])
    assert tech[0].context is None
    probe = normalise_batch(
        batch(
            q("A", source=0), q("B", source=2), q("C", source=2), q("D", source=9), q("E", source=1)
        ),
        5,
        "resume_probe",
        ["e1", "e2"],
    )
    assert [(c.text, c.context) for c in probe] == [("B", "e2"), ("E", "e1")]


def test_rule_4_keeps_first_n():
    out = normalise_batch(batch(q("A"), q("B"), q("C")), 2, "technical", [])
    assert [c.text for c in out] == ["A", "B"]


def unit(sim):
    """A unit vector whose dot product with e0 is sim."""
    v = np.zeros(3)
    v[0], v[1] = sim, np.sqrt(1 - sim * sim)
    return v


E0 = np.array([1.0, 0, 0])


def test_drop_duplicates_against_existing():
    cands = np.stack([unit(0.82), unit(0.81)])
    assert drop_duplicates(cands, np.stack([E0])) == [1]


def test_drop_duplicates_inside_batch():
    cands = np.stack([E0, unit(0.82), unit(0.81)])
    assert drop_duplicates(cands, np.zeros((0, 3))) == [0, 2]


def test_rule_6_no_question_left_is_invalid(client, conn, settings, monkeypatch):
    pid = ready_profile(client)
    topic = topic_row(conn, pid, "Python")
    calls = []

    def fake_chat(provider, model, system, user, schema, *, settings, creative, check):
        calls.append(1)
        try:
            check(batch(q(" ")))
        except llm.InvalidReply:
            pass
        try:
            check(batch(q(" ")))
        except llm.InvalidReply:
            raise llm.LLMOutputError("twice") from None

    monkeypatch.setattr(llm, "chat", fake_chat)
    with pytest.raises(llm.LLMOutputError):
        questions.generate(conn, topic, 3, "easy", "fake", "fake", random.Random(1), settings)
    assert conn.execute("SELECT count(*) FROM questions").fetchone()[0] == 0


def test_generate_stores_questions_with_embeddings(client, conn, settings):
    pid = ready_profile(client)
    topic = topic_row(conn, pid, "Python")
    ids = questions.generate(conn, topic, 3, "medium", "fake", "fake", random.Random(1), settings)
    rows = conn.execute("SELECT * FROM questions ORDER BY id").fetchall()
    assert [r["id"] for r in rows] == ids and len(ids) == 3
    for r in rows:
        assert r["difficulty"] == "medium"
        assert len(r["embedding"]) == 1536
        assert r["context"] is None
        assert len(json.loads(r["key_points"])) == 3


def capture_prompts(monkeypatch):
    prompts = []
    real = llm.chat

    def spy(provider, model, system, user, schema, **kw):
        prompts.append(user)
        return real(provider, model, system, user, schema, **kw)

    monkeypatch.setattr(llm, "chat", spy)
    return prompts


def test_resume_probe_contexts_differ_and_come_from_chunks(client, conn, settings):
    pid = ready_profile(client)
    topic = topic_row(conn, pid, "Resume deep-dive")
    questions.generate(conn, topic, 3, "easy", "fake", "fake", random.Random(7), settings)
    contexts = [r[0] for r in conn.execute("SELECT context FROM questions")]
    chunks = {
        r[0] for r in conn.execute("SELECT text FROM resume_chunks WHERE profile_id = ?", (pid,))
    }
    assert len(contexts) == len(set(contexts)) >= 1
    assert set(contexts) <= chunks


def test_seeded_excerpts_are_reproducible(client, conn, settings, monkeypatch):
    pid = ready_profile(client)
    with conn:  # Give the profile several long chunks to choose from.
        for i in range(6):
            conn.execute(
                "INSERT INTO resume_chunks (profile_id, ord, text) VALUES (?, ?, ?)",
                (pid, 100 + i, f"Extra chunk {i} " + "detail " * 20),
            )
    topic = topic_row(conn, pid, "Resume deep-dive")
    a = questions.choose_excerpts(conn, topic, 3, random.Random(42), settings)
    b = questions.choose_excerpts(conn, topic, 3, random.Random(42), settings)
    assert a == b and len(a[0]) == 3


def test_probe_lowers_n_to_available_chunks(client, conn, settings):
    pid = ready_profile(client)
    topic = topic_row(conn, pid, "Resume deep-dive")
    available = conn.execute(
        "SELECT count(*) FROM resume_chunks WHERE profile_id = ? AND length(text) >= 80", (pid,)
    ).fetchone()[0]
    excerpts, n = questions.choose_excerpts(conn, topic, 10, random.Random(1), settings)
    assert n == available == len(excerpts)


def test_excerpt_under_floor_is_not_sent(client, conn, settings, monkeypatch):
    pid = ready_profile(client)
    with conn:
        conn.execute("DELETE FROM resume_chunks WHERE profile_id = ?", (pid,))
    from app.embeddings import fake_embed, to_blob

    with conn:
        for i, text in enumerate(["Kafka streaming pipelines", "violet harbor lantern"]):
            conn.execute(
                "INSERT INTO resume_chunks (profile_id, ord, text, embedding) VALUES (?, ?, ?, ?)",
                (pid, i, text, to_blob(fake_embed([text])[0])),
            )
        conn.execute("UPDATE topics SET rationale = 'Kafka streaming' WHERE name = 'Python'")
    prompts = capture_prompts(monkeypatch)
    topic = topic_row(conn, pid, "Python")
    questions.generate(conn, topic, 2, "easy", "fake", "fake", random.Random(1), settings)
    sent = prompts[0].split("<excerpts>")[1].split("</excerpts>")[0]
    assert "violet" not in sent
    assert "Kafka streaming pipelines" in sent


def test_other_profiles_questions_are_ignored(client, conn, settings, monkeypatch):
    a = ready_profile(client, "A")
    b = ready_profile(client, "B")
    ta, tb = topic_row(conn, a, "Python"), topic_row(conn, b, "Python")
    questions.generate(conn, tb, 3, "easy", "fake", "fake", random.Random(1), settings)
    b_texts = [r[0] for r in conn.execute("SELECT text FROM questions")]
    assert questions.already_asked(conn, ta["id"]) == []
    assert len(questions.profile_question_vectors(conn, a)) == 0
    prompts = capture_prompts(monkeypatch)
    questions.generate(conn, ta, 2, "easy", "fake", "fake", random.Random(1), settings)
    assert all(t not in prompts[0] for t in b_texts)


def test_already_asked_is_sent(client, conn, settings, monkeypatch):
    pid = ready_profile(client)
    topic = topic_row(conn, pid, "Python")
    questions.generate(conn, topic, 2, "easy", "fake", "fake", random.Random(1), settings)
    first = [r[0] for r in conn.execute("SELECT text FROM questions")]
    prompts = capture_prompts(monkeypatch)
    questions.generate(conn, topic, 2, "easy", "fake", "fake", random.Random(1), settings)
    asked = prompts[0].split("<already_asked>")[1]
    assert all(f"- {t}" in asked for t in first)


def test_near_copy_of_stored_question_is_dropped(client, conn, settings, monkeypatch):
    pid = ready_profile(client)
    topic = topic_row(conn, pid, "Python")
    ids = questions.generate(conn, topic, 1, "easy", "fake", "fake", random.Random(1), settings)
    stored = conn.execute("SELECT text FROM questions WHERE id = ?", (ids[0],)).fetchone()[0]

    def same_again(provider, model, system, user, schema, *, settings, creative, check):
        return check(batch(q(stored), q("A brand new different question about decorators")))

    monkeypatch.setattr(llm, "chat", same_again)
    new = questions.generate(conn, topic, 2, "easy", "fake", "fake", random.Random(1), settings)
    texts = [
        conn.execute("SELECT text FROM questions WHERE id = ?", (i,)).fetchone()[0] for i in new
    ]
    assert texts == ["A brand new different question about decorators"]
