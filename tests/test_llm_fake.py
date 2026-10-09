from dataclasses import replace

import numpy as np
import pytest

from app import llm
from app.embeddings import fake_embed
from app.prompts import (
    Evaluation,
    Plan,
    QuestionBatch,
    evaluation_prompt,
    plan_prompt,
    questions_prompt,
)
from app.scoring import DEDUPE_COSINE, answer_score


def evaluate(settings, answer, left=2):
    system, user = evaluation_prompt("technical", left, "Q?", ["a"], "ref", [], [], "Q?", answer)
    return llm.chat("fake", "fake", system, user, Evaluation, settings=settings)


@pytest.mark.parametrize(
    ("answer", "dims", "score"),
    [
        ("plain answer", (3, 3, 3, 3), 75),
        ("#strong answer", (4, 4, 4, 4), 100),
        ("#weak answer", (1, 1, 1, 1), 25),
        ("#wrong answer", (0, 3, 3, 3), 20),
    ],
)
def test_tags_give_documented_dimensions(settings, answer, dims, score):
    e = evaluate(settings, answer)
    assert (e.correctness, e.depth, e.clarity, e.structure) == dims
    for kind in ("technical", "behavioral", "resume_probe"):
        assert answer_score(kind, *dims) == score


def test_followup_only_while_follow_ups_left(settings):
    assert evaluate(settings, "x #followup", left=2).follow_up == "Fake follow-up: tell me more."
    assert evaluate(settings, "x #followup", left=1).follow_up
    assert evaluate(settings, "x #followup", left=0).follow_up == ""
    assert evaluate(settings, "x", left=2).follow_up == ""


def test_invalid_and_down_raise(settings):
    with pytest.raises(llm.LLMOutputError):
        evaluate(settings, "x #invalid")
    with pytest.raises(llm.LLMUnavailable):
        evaluate(settings, "x #down")


def test_tags_in_earlier_turns_are_ignored(settings):
    system, user = evaluation_prompt(
        "technical", 1, "Q?", [], None, [], [("Q?", "#down #strong")], "F?", "plain"
    )
    e = llm.chat("fake", "fake", system, user, Evaluation, settings=settings)
    assert e.correctness == 3


def test_fake_questions_are_never_near_copies(settings):
    texts = []
    while len(texts) < 200:
        system, user = questions_prompt("Python", "technical", "easy", 5, "", [], [])
        batch = llm.chat("fake", "fake", system, user, QuestionBatch, settings=settings)
        assert len(batch.questions) == 5
        texts += [q.text for q in batch.questions]
    vectors = fake_embed(texts)
    sims = vectors @ vectors.T
    np.fill_diagonal(sims, 0)
    assert sims.max() < DEDUPE_COSINE
    assert len(set(texts)) == 200


def test_fake_question_sources(settings):
    system, user = questions_prompt(
        "Resume deep-dive", "resume_probe", "easy", 3, "", ["a", "b", "c"], []
    )
    batch = llm.chat("fake", "fake", system, user, QuestionBatch, settings=settings)
    assert [q.source for q in batch.questions] == [1, 2, 3]
    assert all(len(q.key_points) == 3 for q in batch.questions)
    system, user = questions_prompt("Python", "technical", "easy", 2, "", [], [])
    batch = llm.chat("fake", "fake", system, user, QuestionBatch, settings=settings)
    assert [q.source for q in batch.questions] == [0, 0]


def test_plan_gains_kubernetes_with_job_description(settings):
    system, user = plan_prompt("resume", None, [])
    plain = llm.chat("fake", "fake", system, user, Plan, settings=settings)
    assert [t.name for t in plain.topics] == [
        "Python",
        "SQL",
        "System design",
        "Testing",
        "Teamwork",
        "Ownership",
    ]
    assert {t.source for t in plain.topics} == {"resume"}
    system, user = plan_prompt("resume", "We need Kubernetes", [])
    with_jd = llm.chat("fake", "fake", system, user, Plan, settings=settings)
    names = {t.name: t for t in with_jd.topics}
    assert names["Kubernetes"].source == "jd" and names["Kubernetes"].weight == 4
    assert names["Python"].source == "both"


def test_fake_provider_refused_outside_fake_mode(settings):
    with pytest.raises(llm.LLMUnavailable):
        llm.chat("fake", "fake", "s", "u", Plan, settings=replace(settings, dev_fake=False))


def test_list_models_never_offers_fake_outside_fake_mode(settings, monkeypatch):
    import httpx

    monkeypatch.setattr(
        llm,
        "http_transport",
        httpx.MockTransport(lambda r: httpx.Response(200, json={"models": []})),
    )
    providers = {o.provider for o in llm.list_models(replace(settings, dev_fake=False))}
    assert "fake" not in providers
    assert {o.provider for o in llm.list_models(settings)} == {"fake"}
